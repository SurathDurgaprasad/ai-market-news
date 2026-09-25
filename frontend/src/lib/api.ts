/**
 * Centralized API configuration for AI Market News.
 *
 * The backend API is served at /api/v1 — all frontend fetch calls must use
 * this base URL to avoid the mismatch with the plain /events/ path.
 *
 * In production, NEXT_PUBLIC_API_BASE_URL should be set to the backend origin.
 * In local development it defaults to http://localhost:8000.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export const API_V1 = `${API_BASE_URL}/api/v1`;
