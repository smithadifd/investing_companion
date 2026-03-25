"""Authentication API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import (
    get_client_ip,
    get_current_user,
    get_user_agent,
    require_not_demo,
)
from app.core.rate_limit import check_login_rate_limit, reset_login_rate_limit
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import (
    PasswordChange,
    RegistrationStatus,
    SessionInfo,
    TokenRefresh,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from app.schemas.common import DataResponse, ResponseMeta
from app.services.auth import AuthService

router = APIRouter()


@router.get("/registration-status", response_model=DataResponse[RegistrationStatus])
async def get_registration_status() -> DataResponse[RegistrationStatus]:
    """Check if registration is enabled."""
    enabled = settings.REGISTRATION_ENABLED and not settings.DEMO_MODE
    if settings.DEMO_MODE:
        message = "Registration is disabled in demo mode"
    elif settings.REGISTRATION_ENABLED:
        message = "Registration is open"
    else:
        message = "Registration is disabled"
    status_data = RegistrationStatus(enabled=enabled, message=message)
    return DataResponse(data=status_data, meta=ResponseMeta.now())


@router.post("/register", response_model=DataResponse[UserResponse], status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    _demo_guard: None = Depends(require_not_demo),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[UserResponse]:
    """Register a new user account."""
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently disabled",
        )

    auth_service = AuthService(db)

    # Check if email already exists
    existing_user = await auth_service.get_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await auth_service.create_user(user_data)
    user_response = UserResponse.model_validate(user)
    return DataResponse(data=user_response, meta=ResponseMeta.now())


@router.post("/login", response_model=DataResponse[TokenResponse])
async def login(
    credentials: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[TokenResponse]:
    """Authenticate and get access/refresh tokens."""
    # Check rate limit before attempting authentication
    await check_login_rate_limit(request, email=credentials.email)

    auth_service = AuthService(db)

    user = await auth_service.authenticate(credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Reset rate limit on successful login
    await reset_login_rate_limit(request, credentials.email)

    tokens = await auth_service.create_session(
        user,
        user_agent=get_user_agent(request),
        ip_address=get_client_ip(request),
    )

    return DataResponse(data=tokens, meta=ResponseMeta.now())


@router.post("/refresh", response_model=DataResponse[TokenResponse])
async def refresh_tokens(
    token_data: TokenRefresh,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[TokenResponse]:
    """Refresh access token using refresh token."""
    auth_service = AuthService(db)

    tokens = await auth_service.refresh_tokens(
        token_data.refresh_token,
        user_agent=get_user_agent(request),
        ip_address=get_client_ip(request),
    )

    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    return DataResponse(data=tokens, meta=ResponseMeta.now())


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token_data: TokenRefresh,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Logout by revoking the refresh token."""
    auth_service = AuthService(db)
    await auth_service.revoke_session(token_data.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Logout from all sessions."""
    auth_service = AuthService(db)
    await auth_service.revoke_all_sessions(current_user.id)


@router.get("/me", response_model=DataResponse[UserResponse])
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> DataResponse[UserResponse]:
    """Get current authenticated user's profile."""
    user_response = UserResponse.model_validate(current_user)
    return DataResponse(data=user_response, meta=ResponseMeta.now())


@router.patch("/me", response_model=DataResponse[UserResponse])
async def update_current_user(
    user_update: UserUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[UserResponse]:
    """Update current user's profile."""
    auth_service = AuthService(db)

    if user_update.email:
        success = await auth_service.update_email(current_user, user_update.email)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )

    await db.refresh(current_user)
    user_response = UserResponse.model_validate(current_user)
    return DataResponse(data=user_response, meta=ResponseMeta.now())


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    password_data: PasswordChange,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change current user's password."""
    auth_service = AuthService(db)

    success = await auth_service.change_password(
        current_user,
        password_data.current_password,
        password_data.new_password,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )


@router.get("/me/sessions", response_model=DataResponse[List[SessionInfo]])
async def get_my_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[List[SessionInfo]]:
    """Get all active sessions for current user."""
    auth_service = AuthService(db)
    sessions = await auth_service.get_user_sessions(current_user.id)

    # Determine current session by IP/user-agent match
    current_ip = get_client_ip(request)
    current_ua = get_user_agent(request)

    session_list = []
    for session in sessions:
        is_current = (
            session.ip_address == current_ip and
            session.user_agent == current_ua
        )
        session_info = SessionInfo(
            id=session.id,
            user_agent=session.user_agent,
            ip_address=session.ip_address,
            created_at=session.created_at,
            expires_at=session.expires_at,
            is_current=is_current,
        )
        session_list.append(session_info)

    return DataResponse(data=session_list, meta=ResponseMeta.now())
