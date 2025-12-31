import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../../components/ui/alert-dialog";
import { doctorsApi } from "../../services/api";
import type { Doctor, DoctorCreate, DoctorRole } from "../../types";
import {
  ArrowLeft,
  Plus,
  Pencil,
  Trash2,
  Search,
  AlertTriangle,
  UserPlus,
} from "lucide-react";
import axios from "axios";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const DoctorsManagement = () => {
  const navigate = useNavigate();
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Pagination and filters
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [activeFilter, setActiveFilter] = useState<"true" | "false" | "all">(
    "all"
  );
  const [userRoleFilter, setUserRoleFilter] = useState<string>("all");
  const [userActiveFilter, setUserActiveFilter] = useState<string>("all");
  const [isHeadFilter, setIsHeadFilter] = useState<string>("all");

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingDoctor, setEditingDoctor] = useState<Doctor | null>(null);
  const [formData, setFormData] = useState<DoctorCreate>({
    first_name: "",
    last_name: "",
    role: "resident",
    is_active: true,
    is_head: false,
    email: "",
    user_role: "doctor",
  });

  // Delete confirmation state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [doctorToDelete, setDoctorToDelete] = useState<Doctor | null>(null);

  // Pending doctors count
  const [pendingCount, setPendingCount] = useState(0);

  // Fetch doctors
  const fetchDoctors = async () => {
    try {
      setLoading(true);
      const params = {
        page,
        size: 20,
        ...(search && { search }),
        ...(roleFilter !== "all" && { role: roleFilter }),
        is_active: activeFilter,
        ...(userRoleFilter !== "all" && { user_role: userRoleFilter }),
        ...(userActiveFilter !== "all" && { user_is_active: userActiveFilter }),
        ...(isHeadFilter !== "all" && { is_head: isHeadFilter }),
      };
      const response = await doctorsApi.list(params);
      setDoctors(response.items);
      setTotal(response.total);
      setError("");
    } catch (err: any) {
      setError("Failed to load doctors");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDoctors();
  }, [
    page,
    search,
    roleFilter,
    activeFilter,
    userRoleFilter,
    userActiveFilter,
    isHeadFilter,
  ]);

  // Load pending doctors count
  useEffect(() => {
    const loadPendingCount = async () => {
      try {
        const token = localStorage.getItem("access_token");
        const response = await axios.get(
          `${API_BASE_URL}/api/v1/admin/pending-doctors/count`,
          {
            headers: { Authorization: `Bearer ${token}` },
          }
        );
        setPendingCount(response.data.count);
      } catch (err) {
        console.error("Failed to load pending count:", err);
      }
    };

    loadPendingCount();
    // Refresh count every 30 seconds
    const interval = setInterval(loadPendingCount, 30000);
    return () => clearInterval(interval);
  }, []);

  // Handle create/update
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingDoctor) {
        await doctorsApi.update(editingDoctor.id, formData);
      } else {
        await doctorsApi.create(formData);
      }
      setIsModalOpen(false);
      setEditingDoctor(null);
      resetForm();
      fetchDoctors();
    } catch (err: any) {
      let errorMsg = "Failed to save doctor";
      if (err.response?.data?.detail) {
        if (typeof err.response.data.detail === "string") {
          errorMsg = err.response.data.detail;
        } else if (err.response.data.detail.detail) {
          errorMsg = err.response.data.detail.detail;
        }
      }
      alert(errorMsg);
    }
  };

  // Open delete confirmation dialog
  const openDeleteDialog = (doctor: Doctor) => {
    setDoctorToDelete(doctor);
    setDeleteDialogOpen(true);
  };

  // Handle delete confirmation
  const confirmDelete = async () => {
    if (!doctorToDelete) return;

    try {
      await doctorsApi.delete(doctorToDelete.id);
      setDeleteDialogOpen(false);
      setDoctorToDelete(null);
      fetchDoctors();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to delete doctor");
      setDeleteDialogOpen(false);
      setDoctorToDelete(null);
    }
  };

  const openCreateModal = () => {
    resetForm();
    setEditingDoctor(null);
    setIsModalOpen(true);
  };

  const openEditModal = (doctor: Doctor) => {
    setFormData({
      first_name: doctor.first_name,
      last_name: doctor.last_name,
      role: doctor.role,
      is_active: doctor.is_active,
      is_head: doctor.is_head,
      email: doctor.email || "",
      user_role: doctor.user_role || "doctor",
      user_is_active:
        doctor.user_is_active !== undefined ? doctor.user_is_active : true,
    } as any);
    setEditingDoctor(doctor);
    setIsModalOpen(true);
  };

  const resetForm = () => {
    setFormData({
      first_name: "",
      last_name: "",
      role: "resident",
      is_active: true,
      is_head: false,
      email: "",
      user_role: "doctor",
    });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminHeader />
      <main className="container mx-auto px-4 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/admin")}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <h2 className="text-3xl font-bold">Manage Doctors</h2>
          </div>
          <div className="flex items-center space-x-3">
            <Button
              variant="outline"
              onClick={() => navigate("/admin/pending-doctors")}
              className="relative"
            >
              <UserPlus className="h-4 w-4 mr-2" />
              Pending Registrations
              {pendingCount > 0 && (
                <span className="absolute -top-2 -right-2 bg-red-600 text-white text-xs font-bold rounded-full h-6 w-6 flex items-center justify-center">
                  {pendingCount}
                </span>
              )}
            </Button>
            <Button onClick={openCreateModal}>
              <Plus className="h-4 w-4 mr-2" />
              Add Doctor
            </Button>
          </div>
        </div>

        {/* Filters */}
        <Card className="mb-6">
          <CardContent className="pt-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div>
                <Label htmlFor="search">Search</Label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="search"
                    placeholder="Search by name or email..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="pl-10"
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="role">Doctor Role</Label>
                <select
                  id="role"
                  value={roleFilter}
                  onChange={(e) => setRoleFilter(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All Roles</option>
                  <option value="specialist">Specialist</option>
                  <option value="resident">Resident</option>
                </select>
              </div>
              <div>
                <Label htmlFor="active">Scheduling Status</Label>
                <select
                  id="active"
                  value={activeFilter}
                  onChange={(e) => setActiveFilter(e.target.value as any)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All</option>
                  <option value="true">Active</option>
                  <option value="false">Inactive</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <Label htmlFor="userRole">User Role</Label>
                <select
                  id="userRole"
                  value={userRoleFilter}
                  onChange={(e) => setUserRoleFilter(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All User Roles</option>
                  <option value="doctor">Doctor</option>
                  <option value="doctor_admin">Doctor Admin</option>
                </select>
              </div>
              <div>
                <Label htmlFor="userActive">Login Status</Label>
                <select
                  id="userActive"
                  value={userActiveFilter}
                  onChange={(e) => setUserActiveFilter(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All</option>
                  <option value="true">Can Login</option>
                  <option value="false">Cannot Login</option>
                </select>
              </div>
              <div>
                <Label htmlFor="isHead">Head of Department</Label>
                <select
                  id="isHead"
                  value={isHeadFilter}
                  onChange={(e) => setIsHeadFilter(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Doctors Table */}
        <Card>
          <CardHeader>
            <CardTitle>Doctors ({total})</CardTitle>
            <CardDescription>
              View and manage all doctors in the system
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-center py-8">Loading...</div>
            ) : error ? (
              <div className="text-center py-8 text-red-600">{error}</div>
            ) : doctors.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No doctors found
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-3 px-4">ID</th>
                      <th className="text-left py-3 px-4">Name</th>
                      <th className="text-left py-3 px-4">Doctor Role</th>
                      <th className="text-left py-3 px-4">User Role</th>
                      <th className="text-left py-3 px-4">Email</th>
                      <th className="text-left py-3 px-4">Scheduling</th>
                      <th className="text-left py-3 px-4">Login</th>
                      <th className="text-left py-3 px-4">Head</th>
                      <th className="text-right py-3 px-4">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {doctors.map((doctor) => (
                      <tr
                        key={doctor.id}
                        className="border-b hover:bg-muted/50"
                      >
                        <td className="py-3 px-4">{doctor.id}</td>
                        <td className="py-3 px-4 font-medium">
                          {doctor.first_name} {doctor.last_name}
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-1 text-xs rounded ${
                              doctor.role === "specialist"
                                ? "bg-blue-100 text-blue-700"
                                : "bg-green-100 text-green-700"
                            }`}
                          >
                            {doctor.role}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {doctor.user_role ? (
                            <span
                              className={`px-2 py-1 text-xs rounded ${
                                doctor.user_role === "admin"
                                  ? "bg-purple-100 text-purple-700"
                                  : doctor.user_role === "doctor_admin"
                                  ? "bg-orange-100 text-orange-700"
                                  : "bg-blue-100 text-blue-700"
                              }`}
                            >
                              {doctor.user_role === "doctor_admin"
                                ? "doc-admin"
                                : doctor.user_role}
                            </span>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td className="py-3 px-4 text-sm text-muted-foreground">
                          {doctor.email || "-"}
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-1 text-xs rounded ${
                              doctor.is_active
                                ? "bg-green-100 text-green-700"
                                : "bg-gray-100 text-gray-700"
                            }`}
                            title="Active in scheduling algorithm"
                          >
                            {doctor.is_active ? "Yes" : "No"}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {doctor.user_is_active !== null &&
                          doctor.user_is_active !== undefined ? (
                            <span
                              className={`px-2 py-1 text-xs rounded ${
                                doctor.user_is_active
                                  ? "bg-green-100 text-green-700"
                                  : "bg-red-100 text-red-700"
                              }`}
                              title="Can login to system"
                            >
                              {doctor.user_is_active ? "Yes" : "No"}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              -
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          {doctor.is_head ? "✓" : "-"}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditModal(doctor)}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openDeleteDialog(doctor)}
                          >
                            <Trash2 className="h-4 w-4 text-red-600" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {total > 20 && (
              <div className="flex justify-between items-center mt-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {page} of {Math.ceil(total / 20)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= Math.ceil(total / 20)}
                >
                  Next
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Modal */}
        {isModalOpen && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <Card className="w-full max-w-md">
              <CardHeader>
                <CardTitle>
                  {editingDoctor ? "Edit Doctor" : "Add New Doctor"}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="first_name">First Name *</Label>
                      <Input
                        id="first_name"
                        value={formData.first_name}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            first_name: e.target.value,
                          })
                        }
                        required
                      />
                    </div>
                    <div>
                      <Label htmlFor="last_name">Last Name *</Label>
                      <Input
                        id="last_name"
                        value={formData.last_name}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            last_name: e.target.value,
                          })
                        }
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <Label htmlFor="email">Email *</Label>
                    <Input
                      id="email"
                      type="email"
                      value={formData.email || ""}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          email: e.target.value,
                        })
                      }
                      required
                    />
                  </div>

                  <div>
                    <Label htmlFor="role">Doctor Role *</Label>
                    <select
                      id="role"
                      value={formData.role}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          role: e.target.value as DoctorRole,
                        })
                      }
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      required
                    >
                      <option value="resident">Resident</option>
                      <option value="specialist">Specialist</option>
                    </select>
                  </div>

                  <div>
                    <Label htmlFor="user_role">User Role *</Label>
                    <select
                      id="user_role"
                      value={(formData as any).user_role || "doctor"}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          user_role: e.target.value as any,
                        } as any)
                      }
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      required={!editingDoctor}
                    >
                      <option value="doctor">Doctor</option>
                      <option value="doctor_admin">Doctor Admin</option>
                    </select>
                    <p className="text-xs text-muted-foreground mt-1">
                      Doctor: can view schedules. Doctor Admin: can also manage
                      preferences.
                    </p>
                  </div>

                  <div className="space-y-2 border-t pt-3">
                    <Label className="text-sm font-semibold">
                      Status Settings
                    </Label>
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="is_active"
                        checked={formData.is_active}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            is_active: e.target.checked,
                          })
                        }
                        className="h-4 w-4"
                      />
                      <Label htmlFor="is_active" className="font-normal">
                        Active in Scheduling
                      </Label>
                    </div>
                    <p className="text-xs text-muted-foreground ml-6">
                      Include this doctor in the scheduling algorithm
                    </p>

                    {editingDoctor && (
                      <>
                        <div className="flex items-center space-x-2">
                          <input
                            type="checkbox"
                            id="user_is_active"
                            checked={(formData as any).user_is_active !== false}
                            onChange={(e) =>
                              setFormData({
                                ...formData,
                                user_is_active: e.target.checked,
                              } as any)
                            }
                            className="h-4 w-4"
                          />
                          <Label
                            htmlFor="user_is_active"
                            className="font-normal"
                          >
                            Can Login
                          </Label>
                        </div>
                        <p className="text-xs text-muted-foreground ml-6">
                          Allow this user to log in to the system
                        </p>
                      </>
                    )}
                  </div>

                  <div className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      id="is_head"
                      checked={formData.is_head}
                      onChange={(e) =>
                        setFormData({ ...formData, is_head: e.target.checked })
                      }
                      className="h-4 w-4"
                    />
                    <Label htmlFor="is_head">Head of Department</Label>
                  </div>

                  <div className="flex space-x-2 pt-4">
                    <Button type="submit" className="flex-1">
                      {editingDoctor ? "Update" : "Create"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="flex-1"
                      onClick={() => {
                        setIsModalOpen(false);
                        setEditingDoctor(null);
                        resetForm();
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Delete Confirmation Dialog */}
        <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <div className="flex items-center space-x-2">
                <AlertTriangle className="h-5 w-5 text-red-600" />
                <AlertDialogTitle>Are you sure?</AlertDialogTitle>
              </div>
              <AlertDialogDescription>
                {doctorToDelete && (
                  <>
                    This will permanently delete{" "}
                    <strong>
                      {doctorToDelete.first_name} {doctorToDelete.last_name}
                    </strong>
                    . This action cannot be undone.
                  </>
                )}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={confirmDelete}
                className="bg-red-600 hover:bg-red-700"
              >
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </main>
    </div>
  );
};
