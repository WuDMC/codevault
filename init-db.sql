-- PostgreSQL initialization script
-- Runs automatically when postgres container starts for the first time

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tables will be created automatically by `memory init` or by the application
-- This file just ensures extensions are loaded

-- Optional: create additional schemas for other applications
-- CREATE SCHEMA IF NOT EXISTS other_app;

-- Optional: create additional users for other applications
-- CREATE USER other_app_user WITH PASSWORD 'password';
-- GRANT ALL PRIVILEGES ON SCHEMA other_app TO other_app_user;
