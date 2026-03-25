export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

export const DEMO_USER = {
  email: 'demo@example.com',
  password: 'demo1234!',
} as const;

export const DEMO_REPO_URL = 'https://github.com/smithadifd/investing_companion';
