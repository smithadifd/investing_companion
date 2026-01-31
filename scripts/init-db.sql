-- Investing Companion - Database Initialization
-- This script runs on first container start

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgcrypto for encryption
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Verify extensions
SELECT * FROM pg_extension WHERE extname IN ('timescaledb', 'uuid-ossp', 'pgcrypto');
