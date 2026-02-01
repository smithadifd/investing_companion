# Investing Companion - Security Guide

## Overview

This document covers security considerations and best practices for deploying Investing Companion.

---

## Security Features

### Authentication

- **Password Hashing**: Argon2id (winner of the Password Hashing Competition)
- **JWT Access Tokens**: 30-minute expiry, HS256 signing
- **Refresh Tokens**: 30-day expiry, SHA-256 hashed storage
- **Session Tracking**: IP address and user agent logged

### Rate Limiting

- **Login Endpoint**:
  - 20 attempts per IP per 15 minutes
  - 5 attempts per email per 15 minutes
- **API Rate Limit** (Traefik): 100 requests/second average, 50 burst

### Security Headers

All responses include:
- `X-Frame-Options: DENY` - Prevents clickjacking
- `X-Content-Type-Options: nosniff` - Prevents MIME sniffing
- `X-XSS-Protection: 1; mode=block` - XSS protection for older browsers
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` - Restricts browser features
- `Strict-Transport-Security` (production only) - Forces HTTPS

### Data Protection

- **API Keys**: Encrypted at rest with Fernet (AES-128-CBC)
- **Database**: Not exposed to internet (internal Docker network only)
- **Redis**: Not exposed to internet (internal Docker network only)

---

## Production Security Checklist

### Before Deployment

- [ ] Generate secure `SECRET_KEY` (32+ characters)
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- [ ] Generate secure `POSTGRES_PASSWORD`
  ```bash
  openssl rand -base64 24
  ```

- [ ] Verify `.env.production` is in `.gitignore`

- [ ] Review and update `.env.production` settings

### Network Security

- [ ] Only ports 80 and 443 exposed to internet
- [ ] Database port (5432) NOT forwarded
- [ ] Redis port (6379) NOT forwarded
- [ ] API port (8000) NOT directly accessible (only via Traefik)

### After Deployment

- [ ] HTTPS working correctly (check certificate)
  ```bash
  curl -I https://your-domain.com
  ```

- [ ] Registration disabled (after creating your account)
  ```bash
  REGISTRATION_ENABLED=false
  ```

- [ ] Health endpoint accessible
  ```bash
  curl https://your-domain.com/health?detailed=true
  ```

- [ ] Rate limiting working
  ```bash
  # Should get 429 after many rapid attempts
  for i in {1..25}; do curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST https://your-domain.com/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"test@test.com","password":"wrong"}'; done
  ```

---

## Secrets Management

### What Needs Protection

| Secret | Location | Impact if Leaked |
|--------|----------|------------------|
| `SECRET_KEY` | `.env.production` | JWT forgery, account takeover |
| `POSTGRES_PASSWORD` | `.env.production` | Database access |
| `DISCORD_WEBHOOK_URL` | `.env.production`, user_settings | Alert spam |
| `CLAUDE_API_KEY` | `.env.production`, user_settings | API billing |
| User API keys | Database (encrypted) | Service abuse |

### Rotation Procedures

**SECRET_KEY Rotation:**
1. Generate new key
2. Update `.env.production`
3. Restart API container
4. All users will need to re-login (tokens invalidated)

**Database Password Rotation:**
1. Generate new password
2. Update password in PostgreSQL:
   ```sql
   ALTER USER investing_prod PASSWORD 'new_password';
   ```
3. Update `.env.production`
4. Restart all containers

**Discord Webhook Rotation:**
1. Create new webhook in Discord
2. Delete old webhook
3. Update in user settings or `.env.production`
4. Restart if using environment variable

---

## Network Security

### Firewall Configuration

For Synology (Security Advisor):
```
Allow: TCP 80 from any (Let's Encrypt + redirect)
Allow: TCP 443 from any (HTTPS)
Deny: All other inbound from internet
Allow: All internal network (192.168.x.x)
```

### Reverse Proxy (Traefik)

Traefik handles:
- TLS termination
- Certificate management (Let's Encrypt)
- Rate limiting
- Request routing

Do NOT bypass Traefik to access services directly.

### Internal Network

All services communicate via Docker network `investing_network`:
- Database only accepts connections from API/Celery
- Redis only accepts connections from API/Celery
- Frontend proxies API requests through Traefik

---

## Authentication Security

### Password Requirements

Current implementation accepts any password. For stricter requirements, add validation:

```python
# In backend/app/schemas/auth.py
from pydantic import field_validator

class UserCreate(BaseModel):
    password: str

    @field_validator('password')
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError('Password must be at least 12 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain a digit')
        return v
```

### Session Security

- Sessions stored in database with hashed refresh tokens
- Sessions tracked by IP and user agent
- Users can view and revoke sessions in settings
- "Logout all" option available

### Rate Limiting Details

Login rate limiting uses Redis with sliding window:

```
IP-based:    20 attempts per 15 minutes (catches broad attacks)
Email-based: 5 attempts per 15 minutes (protects specific accounts)
```

After successful login, email-based limit is reset.

---

## Data Security

### Encryption at Rest

**API Keys in user_settings:**
- Encrypted with Fernet (AES-128-CBC + HMAC)
- Key derived from `SECRET_KEY`
- Decrypted only when needed

**Database:**
- TimescaleDB supports TDE (not currently enabled)
- Consider enabling for highly sensitive deployments

### Encryption in Transit

- All external traffic via HTTPS (TLS 1.2+)
- Internal Docker traffic unencrypted (acceptable for single-host)
- For multi-host: add TLS to internal services

### Data Retention

Consider implementing:
- Alert history cleanup (older than 1 year)
- Session cleanup (expired sessions)
- Price history compression (older data)

---

## Security Monitoring

### Log Review

Check regularly:

```bash
# API errors
docker logs investing_api 2>&1 | grep -i error

# Authentication failures
docker logs investing_api 2>&1 | grep -i "401\|unauthorized"

# Rate limit hits
docker logs investing_traefik 2>&1 | grep -i "429"
```

### Suspicious Activity

Watch for:
- Many failed login attempts
- Unusual API patterns
- Large data exports
- Settings changes

### Health Monitoring

Set up alerts for:
- Health endpoint failures
- High error rates
- Service restarts

---

## Incident Response

### Suspected Breach

1. **Contain**: Disable registration, consider taking offline
2. **Assess**: Check logs for unauthorized access
3. **Rotate**: All secrets (SECRET_KEY, passwords, API keys)
4. **Notify**: Users if their data was accessed
5. **Review**: How did it happen, how to prevent

### Compromised API Key

1. Revoke key with the provider
2. Generate new key
3. Update in application
4. Review usage logs for abuse

### Lost Database Password

1. Stop all services
2. Access PostgreSQL as postgres user
3. Reset password:
   ```sql
   ALTER USER investing_prod PASSWORD 'new_password';
   ```
4. Update `.env.production`
5. Restart services

---

## Security Updates

### Keeping Updated

```bash
# Update base images
docker compose -f docker-compose.prod.yml pull

# Rebuild with updates
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

# Update Python dependencies (development)
pip install --upgrade -r requirements.txt
```

### Dependency Scanning

Consider adding:
- GitHub Dependabot
- `pip-audit` for Python
- `npm audit` for Node.js

---

## Reporting Security Issues

If you discover a security vulnerability:

1. **Do NOT** create a public GitHub issue
2. Email details to the maintainer
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

---

## Additional Hardening (Advanced)

### Database Constraints

Add CHECK constraints:

```sql
ALTER TABLE trades ADD CONSTRAINT positive_quantity CHECK (quantity > 0);
ALTER TABLE trades ADD CONSTRAINT positive_price CHECK (price > 0);
```

### Content Security Policy

Add CSP headers to frontend:

```javascript
// next.config.js
const securityHeaders = [
  {
    key: 'Content-Security-Policy',
    value: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';"
  }
];
```

### Audit Logging

Consider adding for sensitive operations:
- Login/logout events
- Settings changes
- Trade modifications
- Alert triggers
