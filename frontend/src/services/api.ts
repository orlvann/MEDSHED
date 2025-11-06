import axios, { AxiosInstance, AxiosError } from "axios";
import type {
  LoginRequest,
  TokenResponse,
  User,
  Doctor,
  DoctorCreate,
  DoctorPut,
  DoctorList,
  ErrorPayload,
} from "../types";

// Base API URL - can be overridden by environment variable
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// Create axios instance
const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ErrorPayload>) => {
    if (error.response?.status === 401) {
      // Check if this is a login attempt - don't redirect in that case
      const isLoginRequest = error.config?.url?.includes("/api/v1/auth/login");

      if (!isLoginRequest) {
        // Unauthorized - clear token and redirect to login (only for non-login requests)
        localStorage.removeItem("access_token");
        localStorage.removeItem("user");
        window.location.href = "/login/admin";
      }
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: async (credentials: LoginRequest): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>(
      "/api/v1/auth/login",
      credentials
    );
    return response.data;
  },

  me: async (): Promise<User> => {
    const response = await api.get<User>("/api/v1/auth/me");
    return response.data;
  },
};

// Doctors API
export const doctorsApi = {
  list: async (params: {
    page?: number;
    size?: number;
    role?: string;
    search?: string;
    is_active?: "true" | "false" | "all";
  }): Promise<DoctorList> => {
    const response = await api.get<DoctorList>("/api/v1/doctors", { params });
    return response.data;
  },

  get: async (id: number): Promise<Doctor> => {
    const response = await api.get<Doctor>(`/api/v1/doctors/${id}`);
    return response.data;
  },

  create: async (doctor: DoctorCreate): Promise<Doctor> => {
    const response = await api.post<Doctor>("/api/v1/doctors", doctor);
    return response.data;
  },

  update: async (id: number, doctor: DoctorPut): Promise<Doctor> => {
    const response = await api.put<Doctor>(`/api/v1/doctors/${id}`, doctor);
    return response.data;
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/api/v1/doctors/${id}`);
  },
};

export default api;
