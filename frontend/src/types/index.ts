/**
 * TypeScript types matching the backend API contract
 */

export type Role = "admin" | "doctor" | "doctor_admin";

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
  first_name: string | null;
  last_name: string | null;
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
  user_is_active?: boolean | null;
  user_role?: Role | null;
}

export interface DoctorCreate {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email: string; // Required
  user_role: Role; // Required: "doctor" or "doctor_admin"
}

export interface DoctorPut {
  first_name: string;
  last_name: string;
  role: DoctorRole;
  is_active: boolean;
  is_head: boolean;
  email?: string | null;
  user_role?: Role | null;
  user_is_active?: boolean | null;
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

// Set Password types
export interface SetPasswordRequest {
  token: string;
  new_password: string;
}

export interface SetPasswordResponse {
  message: string;
}

// Admin Users types
export interface AdminUser {
  id: number;
  email: string;
  role: Role;
  is_active: boolean;
  doctor_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserCreate {
  email: string;
  doctor_id?: number | null;
}

export interface AdminUserUpdate {
  email?: string | null;
  is_active?: boolean | null;
  doctor_id?: number | null;
}

export interface AdminUserList {
  page: number;
  size: number;
  total: number;
  items: AdminUser[];
}
