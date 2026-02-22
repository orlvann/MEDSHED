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
  SetPasswordRequest,
  SetPasswordResponse,
  AdminUser,
  AdminUserCreate,
  AdminUserUpdate,
  AdminUserList,
  PreferenceWorkingRead,
  PreferenceWorkingPut,
  PreferenceAutosaveAck,
  PreferenceCheckpointCreated,
  PreferenceRevertRead,
  PreferencesSummaryRead,
  PreferencesDeadlineRead,
  SchedulePublishedRead,
  MyAssignmentsRead,
  AvailabilityOverviewRead,
  AvailabilityDayRead,
  ScheduleGenerateRequest,
  ScheduleGenerateCreated,
  SchedulesPeriodViewRead,
  ScheduleWorkingRead,
  ScheduleWorkingPut,
  ScheduleWorkingAck,
  ScheduleCheckpointRequest,
  ScheduleCheckpointCreated,
  ScheduleRevertRead,
  SchedulePublishRequest,
  SchedulePublishCreated,
  SchedulePublishedRevertRead,
  DiagnosticsRead,
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
  (error) => Promise.reject(error),
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
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

// Auth API
export const authApi = {
  login: async (credentials: LoginRequest): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>(
      "/api/v1/auth/login",
      credentials,
    );
    return response.data;
  },

  me: async (): Promise<User> => {
    const response = await api.get<User>("/api/v1/auth/me");
    return response.data;
  },

  setPassword: async (
    data: SetPasswordRequest,
  ): Promise<SetPasswordResponse> => {
    const response = await api.post<SetPasswordResponse>(
      "/api/v1/auth/set-password",
      data,
    );
    return response.data;
  },

  updateProfile: async (data: {
    first_name?: string;
    last_name?: string;
  }): Promise<User> => {
    const response = await api.patch<User>("/api/v1/auth/me", data);
    return response.data;
  },

  changePassword: async (data: {
    current_password: string;
    new_password: string;
  }): Promise<{ message: string }> => {
    const response = await api.post<{ message: string }>(
      "/api/v1/auth/change-password",
      data,
    );
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

// Admin Users API
export const adminUsersApi = {
  list: async (params: {
    page?: number;
    size?: number;
    search?: string;
  }): Promise<AdminUserList> => {
    const response = await api.get<AdminUserList>("/api/v1/admin/users", {
      params,
    });
    return response.data;
  },

  get: async (id: number): Promise<AdminUser> => {
    const response = await api.get<AdminUser>(`/api/v1/admin/users/${id}`);
    return response.data;
  },

  create: async (user: AdminUserCreate): Promise<AdminUser> => {
    const response = await api.post<AdminUser>("/api/v1/admin/users", user);
    return response.data;
  },

  update: async (id: number, user: AdminUserUpdate): Promise<AdminUser> => {
    const response = await api.put<AdminUser>(
      `/api/v1/admin/users/${id}`,
      user,
    );
    return response.data;
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/api/v1/admin/users/${id}`);
  },
};

// Preferences API (Admin)
export const preferencesApi = {
  // Summary - who submitted vs missing
  getSummary: async (
    year: number,
    month: number,
  ): Promise<PreferencesSummaryRead> => {
    const response = await api.get<PreferencesSummaryRead>(
      "/api/v1/preferences/summary",
      { params: { year, month } },
    );
    return response.data;
  },

  // Deadline management
  getDeadline: async (
    year: number,
    month: number,
  ): Promise<PreferencesDeadlineRead> => {
    const response = await api.get<PreferencesDeadlineRead>(
      `/api/v1/preferences/deadlines/${year}/${month}`,
    );
    return response.data;
  },

  updateDeadline: async (
    year: number,
    month: number,
    deadline: string,
  ): Promise<PreferencesDeadlineRead> => {
    const response = await api.put<PreferencesDeadlineRead>(
      `/api/v1/preferences/deadlines/${year}/${month}`,
      { deadline },
    );
    return response.data;
  },

  // Admin operations for specific doctor
  getWorking: async (
    year: number,
    month: number,
    doctorId: number,
  ): Promise<PreferenceWorkingRead> => {
    const response = await api.get<PreferenceWorkingRead>(
      `/api/v1/preferences/${year}/${month}/${doctorId}`,
    );
    return response.data;
  },

  saveWorking: async (
    year: number,
    month: number,
    doctorId: number,
    data: PreferenceWorkingPut,
  ): Promise<PreferenceAutosaveAck> => {
    const response = await api.put<PreferenceAutosaveAck>(
      `/api/v1/preferences/${year}/${month}/${doctorId}/working`,
      data,
    );
    return response.data;
  },

  createCheckpoint: async (
    year: number,
    month: number,
    doctorId: number,
  ): Promise<PreferenceCheckpointCreated> => {
    const response = await api.post<PreferenceCheckpointCreated>(
      `/api/v1/preferences/${year}/${month}/${doctorId}/checkpoint`,
      {},
    );
    return response.data;
  },

  revertLast: async (
    year: number,
    month: number,
    doctorId: number,
  ): Promise<PreferenceRevertRead> => {
    const response = await api.post<PreferenceRevertRead>(
      `/api/v1/preferences/${year}/${month}/${doctorId}/revert-last`,
    );
    return response.data;
  },

  revertNext: async (
    year: number,
    month: number,
    doctorId: number,
  ): Promise<PreferenceRevertRead> => {
    const response = await api.post<PreferenceRevertRead>(
      `/api/v1/preferences/${year}/${month}/${doctorId}/revert-next`,
    );
    return response.data;
  },
};

// Doctor Preferences API (for /me endpoints)
export const doctorPreferencesApi = {
  getMyPreferences: async (
    year: number,
    month: number,
  ): Promise<PreferenceWorkingRead> => {
    const response = await api.get<PreferenceWorkingRead>(
      `/api/v1/preferences/${year}/${month}/me`,
    );
    return response.data;
  },

  saveMyWorking: async (
    year: number,
    month: number,
    data: PreferenceWorkingPut,
  ): Promise<PreferenceAutosaveAck> => {
    const response = await api.put<PreferenceAutosaveAck>(
      `/api/v1/preferences/${year}/${month}/me/working`,
      data,
    );
    return response.data;
  },

  createMyCheckpoint: async (
    year: number,
    month: number,
  ): Promise<PreferenceCheckpointCreated> => {
    const response = await api.post<PreferenceCheckpointCreated>(
      `/api/v1/preferences/${year}/${month}/me/checkpoint`,
      {},
    );
    return response.data;
  },

  revertMyLast: async (
    year: number,
    month: number,
  ): Promise<PreferenceRevertRead> => {
    const response = await api.post<PreferenceRevertRead>(
      `/api/v1/preferences/${year}/${month}/me/revert-last`,
      {},
    );
    return response.data;
  },

  revertMyNext: async (
    year: number,
    month: number,
  ): Promise<PreferenceRevertRead> => {
    const response = await api.post<PreferenceRevertRead>(
      `/api/v1/preferences/${year}/${month}/me/revert-next`,
      {},
    );
    return response.data;
  },
};

// Schedules API
export const schedulesApi = {
  // Doctor endpoints
  getPublished: async (
    year: number,
    month: number,
  ): Promise<SchedulePublishedRead> => {
    const response = await api.get<SchedulePublishedRead>(
      `/api/v1/schedules/${year}/${month}/published`,
    );
    return response.data;
  },

  getMyAssignments: async (
    year: number,
    month: number,
  ): Promise<MyAssignmentsRead> => {
    const response = await api.get<MyAssignmentsRead>(
      `/api/v1/schedules/${year}/${month}/my-assignments`,
    );
    return response.data;
  },

  exportMySchedule: async (
    year: number,
    month: number,
    format: "xlsx" | "pdf" | "ics",
  ): Promise<Blob> => {
    const response = await api.get(
      `/api/v1/schedules/${year}/${month}/my-export`,
      {
        params: { format },
        responseType: "blob",
      },
    );
    return response.data;
  },

  exportTeamSchedule: async (
    year: number,
    month: number,
    format: "xlsx" | "pdf" | "ics",
    filters?: {
      doctor_id?: number;
      shift_type?: "onsite" | "oncall";
      role?: "specialist" | "resident";
    },
  ): Promise<Blob> => {
    const response = await api.get(
      `/api/v1/schedules/${year}/${month}/team-export`,
      {
        params: { format, ...filters },
        responseType: "blob",
      },
    );
    return response.data;
  },

  getCalendarToken: async (): Promise<{ token: string }> => {
    const response = await api.get<{ token: string }>(
      "/api/v1/schedules/me/calendar-token",
    );
    return response.data;
  },

  regenerateCalendarToken: async (): Promise<{ token: string }> => {
    const response = await api.post<{ token: string }>(
      "/api/v1/schedules/me/calendar-token/regenerate",
    );
    return response.data;
  },

  generate: async (
    data: ScheduleGenerateRequest,
  ): Promise<ScheduleGenerateCreated> => {
    const response = await api.post<ScheduleGenerateCreated>(
      "/api/v1/schedules/generate",
      data,
    );
    return response.data;
  },

  // Admin endpoints — Period View
  getPeriodView: async (
    year: number,
    month: number,
  ): Promise<SchedulesPeriodViewRead> => {
    const response = await api.get<SchedulesPeriodViewRead>(
      `/api/v1/schedules/${year}/${month}`,
    );
    return response.data;
  },

  // Working buffer
  getWorking: async (
    year: number,
    month: number,
  ): Promise<ScheduleWorkingRead> => {
    const response = await api.get<ScheduleWorkingRead>(
      `/api/v1/schedules/${year}/${month}/working`,
    );
    return response.data;
  },

  saveWorking: async (
    year: number,
    month: number,
    data: ScheduleWorkingPut,
  ): Promise<ScheduleWorkingAck> => {
    const response = await api.put<ScheduleWorkingAck>(
      `/api/v1/schedules/${year}/${month}/working`,
      data,
    );
    return response.data;
  },

  // Checkpoint
  checkpoint: async (
    year: number,
    month: number,
    data?: ScheduleCheckpointRequest,
  ): Promise<ScheduleCheckpointCreated> => {
    const response = await api.post<ScheduleCheckpointCreated>(
      `/api/v1/schedules/${year}/${month}/checkpoint`,
      data || {},
    );
    return response.data;
  },

  // Draft undo/redo
  revertDraft: async (
    year: number,
    month: number,
  ): Promise<ScheduleRevertRead> => {
    const response = await api.post<ScheduleRevertRead>(
      `/api/v1/schedules/${year}/${month}/revert-last`,
    );
    return response.data;
  },

  redoDraft: async (
    year: number,
    month: number,
  ): Promise<ScheduleRevertRead> => {
    const response = await api.post<ScheduleRevertRead>(
      `/api/v1/schedules/${year}/${month}/revert-next`,
    );
    return response.data;
  },

  // Publish
  publish: async (
    year: number,
    month: number,
    data: SchedulePublishRequest,
  ): Promise<SchedulePublishCreated> => {
    const response = await api.post<SchedulePublishCreated>(
      `/api/v1/schedules/${year}/${month}/publish`,
      data,
    );
    return response.data;
  },

  // Published undo/redo
  revertPublished: async (
    year: number,
    month: number,
  ): Promise<SchedulePublishedRevertRead> => {
    const response = await api.post<SchedulePublishedRevertRead>(
      `/api/v1/schedules/${year}/${month}/revert-last-published`,
    );
    return response.data;
  },

  redoPublished: async (
    year: number,
    month: number,
  ): Promise<SchedulePublishedRevertRead> => {
    const response = await api.post<SchedulePublishedRevertRead>(
      `/api/v1/schedules/${year}/${month}/revert-next-published`,
    );
    return response.data;
  },

  // Diagnostics
  getDiagnostics: async (
    year: number,
    month: number,
    target: "working" | "draft" | "published",
  ): Promise<DiagnosticsRead> => {
    const response = await api.get<DiagnosticsRead>(
      `/api/v1/schedules/${year}/${month}/diagnostics`,
      { params: { target } },
    );
    return response.data;
  },
};

// Availability API
export const availabilityApi = {
  getOverview: async (
    year: number,
    month: number,
  ): Promise<AvailabilityOverviewRead> => {
    const response = await api.get<AvailabilityOverviewRead>(
      "/api/v1/availability/overview",
      { params: { year, month } },
    );
    return response.data;
  },

  getDay: async (
    year: number,
    month: number,
    day: number,
  ): Promise<AvailabilityDayRead> => {
    const response = await api.get<AvailabilityDayRead>(
      `/api/v1/availability/${year}/${month}/${day}`,
    );
    return response.data;
  },
};

export default api;
