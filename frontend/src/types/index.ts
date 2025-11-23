/**
 * TypeScript types matching the backend API contract
 */

export type Role = "admin" | "doctor";

export type DoctorRole = "specialist" | "resident";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "Bearer";
}

export interface User {
  id: number;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface Doctor {
  id: number;
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email: string | null;
  created_at: string;
  updated_at: string;
}

export interface DoctorCreate {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email?: string | null;
}

export interface DoctorPut {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email?: string | null;
}

export interface DoctorList {
  page: number;
  size: number;
  total: number;
  items: Doctor[];
}

export interface ErrorPayload {
  detail: string;
  code: string;
  context?: Record<string, any>;
}
