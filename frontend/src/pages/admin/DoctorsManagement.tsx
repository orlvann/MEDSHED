import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { useIsMobile } from "../../hooks/useMediaQuery";
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
  SlidersHorizontal,
} from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "../../components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import axios from "axios";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const DoctorsManagement = () => {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
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
    phone_number: "",
    user_role: "doctor",
  });

  // Delete confirmation state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [doctorToDelete, setDoctorToDelete] = useState<Doctor | null>(null);

  // Mobile filter sheet
  const [filtersOpen, setFiltersOpen] = useState(false);
  const activeFilterCount = [
    roleFilter !== "all",
    activeFilter !== "all",
    userRoleFilter !== "all",
    userActiveFilter !== "all",
    isHeadFilter !== "all",
  ].filter(Boolean).length;

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
      phone_number: doctor.phone_number || "",
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
      phone_number: "",
      user_role: "doctor",
    });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminHeader />
      <main className="container mx-auto px-3 sm:px-4 py-4 sm:py-8">
        <div className="mb-4 sm:mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center space-x-3 sm:space-x-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/admin")}
              title="Back"
            >
              <ArrowLeft className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Back</span>
            </Button>
            <h2 className="text-xl sm:text-3xl font-bold">Manage Doctors</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <Button
              variant="outline"
              size={isMobile ? "sm" : "default"}
              onClick={() => navigate("/admin/pending-doctors")}
              className="relative"
            >
              <UserPlus className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Pending Registrations</span>
              <span className="sm:hidden">Pending</span>
              {pendingCount > 0 && (
                <span className="absolute -top-2 -right-2 bg-red-600 text-white text-xs font-bold rounded-full h-5 w-5 sm:h-6 sm:w-6 text-[10px] sm:text-xs flex items-center justify-center">
                  {pendingCount}
                </span>
              )}
            </Button>
            <Button size={isMobile ? "sm" : "default"} onClick={openCreateModal}>
              <Plus className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Add Doctor</span>
              <span className="sm:hidden">Add</span>
            </Button>
          </div>
        </div>

        {/* Filters — mobile: search + sheet toggle; desktop: full card */}
        {isMobile ? (
          <>
            <div className="flex gap-2 mb-4">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9 h-9 text-sm"
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                className="relative shrink-0"
                onClick={() => setFiltersOpen(true)}
              >
                <SlidersHorizontal className="h-4 w-4 mr-1.5" />
                Filters
                {activeFilterCount > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 bg-primary text-primary-foreground text-[10px] font-bold rounded-full h-4 w-4 flex items-center justify-center">
                    {activeFilterCount}
                  </span>
                )}
              </Button>
            </div>

            <Sheet open={filtersOpen} onOpenChange={setFiltersOpen}>
              <SheetContent side="bottom" className="rounded-t-xl max-h-[80vh] overflow-y-auto">
                <SheetHeader className="mb-4">
                  <SheetTitle>Filters</SheetTitle>
                  <SheetDescription>Narrow down the doctors list</SheetDescription>
                </SheetHeader>
                <div className="space-y-4">
                  <div>
                    <Label>Doctor Role</Label>
                    <Select value={roleFilter} onValueChange={setRoleFilter}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All Roles</SelectItem>
                        <SelectItem value="specialist">Specialist</SelectItem>
                        <SelectItem value="resident">Resident</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Scheduling Status</Label>
                    <Select value={activeFilter} onValueChange={(v) => setActiveFilter(v as any)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All</SelectItem>
                        <SelectItem value="true">Active</SelectItem>
                        <SelectItem value="false">Inactive</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>User Role</Label>
                    <Select value={userRoleFilter} onValueChange={setUserRoleFilter}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All User Roles</SelectItem>
                        <SelectItem value="doctor">Doctor</SelectItem>
                        <SelectItem value="doctor_admin">Doctor Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Login Status</Label>
                    <Select value={userActiveFilter} onValueChange={setUserActiveFilter}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All</SelectItem>
                        <SelectItem value="true">Can Login</SelectItem>
                        <SelectItem value="false">Cannot Login</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Head of Department</Label>
                    <Select value={isHeadFilter} onValueChange={setIsHeadFilter}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All</SelectItem>
                        <SelectItem value="true">Yes</SelectItem>
                        <SelectItem value="false">No</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {activeFilterCount > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      onClick={() => {
                        setRoleFilter("all");
                        setActiveFilter("all");
                        setUserRoleFilter("all");
                        setUserActiveFilter("all");
                        setIsHeadFilter("all");
                      }}
                    >
                      Clear All Filters
                    </Button>
                  )}
                </div>
              </SheetContent>
            </Sheet>
          </>
        ) : (
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
                  <Label>Doctor Role</Label>
                  <Select value={roleFilter} onValueChange={setRoleFilter}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Roles</SelectItem>
                      <SelectItem value="specialist">Specialist</SelectItem>
                      <SelectItem value="resident">Resident</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Scheduling Status</Label>
                  <Select value={activeFilter} onValueChange={(v) => setActiveFilter(v as any)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="true">Active</SelectItem>
                      <SelectItem value="false">Inactive</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <Label>User Role</Label>
                  <Select value={userRoleFilter} onValueChange={setUserRoleFilter}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All User Roles</SelectItem>
                      <SelectItem value="doctor">Doctor</SelectItem>
                      <SelectItem value="doctor_admin">Doctor Admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Login Status</Label>
                  <Select value={userActiveFilter} onValueChange={setUserActiveFilter}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="true">Can Login</SelectItem>
                      <SelectItem value="false">Cannot Login</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Head of Department</Label>
                  <Select value={isHeadFilter} onValueChange={setIsHeadFilter}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="true">Yes</SelectItem>
                      <SelectItem value="false">No</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Doctors Table */}
        <Card>
          <CardHeader className="px-4 py-3 sm:px-6 sm:py-6">
            <CardTitle className="text-base sm:text-xl">Doctors ({total})</CardTitle>
            <CardDescription className="text-xs sm:text-sm">
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
            ) : isMobile ? (
              /* Mobile card view */
              <div className="space-y-2">
                {doctors.map((doctor) => (
                  <div key={doctor.id} className="border rounded-lg p-2.5 hover:bg-muted/50">
                    <div className="flex items-start justify-between mb-1.5">
                      <div className="min-w-0 flex-1 mr-2">
                        <p className="text-sm font-medium truncate">
                          {doctor.first_name} {doctor.last_name}
                        </p>
                        <p className="text-xs text-muted-foreground truncate">
                          {doctor.email || "-"}
                        </p>
                      </div>
                      <div className="flex items-center gap-0.5 shrink-0">
                        <Button variant="ghost" size="icon" className="h-8 w-8 p-0" onClick={() => openEditModal(doctor)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-8 w-8 p-0" onClick={() => openDeleteDialog(doctor)}>
                          <Trash2 className="h-3.5 w-3.5 text-red-600" />
                        </Button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <span className={`px-1.5 py-0.5 text-[11px] rounded ${
                        doctor.role === "specialist" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
                      }`}>
                        {doctor.role}
                      </span>
                      {doctor.user_role && (
                        <span className={`px-1.5 py-0.5 text-[11px] rounded ${
                          doctor.user_role === "admin" ? "bg-purple-100 text-purple-700"
                            : doctor.user_role === "doctor_admin" ? "bg-orange-100 text-orange-700"
                            : "bg-blue-100 text-blue-700"
                        }`}>
                          {doctor.user_role === "doctor_admin" ? "doc-admin" : doctor.user_role}
                        </span>
                      )}
                      <span className={`px-1.5 py-0.5 text-[11px] rounded ${
                        doctor.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"
                      }`}>
                        {doctor.is_active ? "Active" : "Inactive"}
                      </span>
                      {doctor.is_head && (
                        <span className="px-1.5 py-0.5 text-[11px] rounded bg-amber-100 text-amber-700">Head</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              /* Desktop table view */
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

        {/* Doctor form modal — Sheet on mobile, Dialog on desktop */}
        {isMobile ? (
          <Sheet open={isModalOpen} onOpenChange={(open) => {
            if (!open) { setIsModalOpen(false); setEditingDoctor(null); resetForm(); }
          }}>
            <SheetContent side="bottom" className="rounded-t-xl max-h-[92vh] overflow-y-auto px-4 pb-6">
              <SheetHeader className="mb-3">
                <SheetTitle>{editingDoctor ? "Edit Doctor" : "Add New Doctor"}</SheetTitle>
                <SheetDescription>
                  {editingDoctor
                    ? `Editing ${editingDoctor.first_name} ${editingDoctor.last_name}`
                    : "Fill in the details to create a new doctor"}
                </SheetDescription>
              </SheetHeader>
              <form onSubmit={handleSubmit} className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label htmlFor="m-first_name" className="text-xs">First Name *</Label>
                    <Input id="m-first_name" value={formData.first_name} onChange={(e) => setFormData({ ...formData, first_name: e.target.value })} required className="h-9 text-sm" />
                  </div>
                  <div>
                    <Label htmlFor="m-last_name" className="text-xs">Last Name *</Label>
                    <Input id="m-last_name" value={formData.last_name} onChange={(e) => setFormData({ ...formData, last_name: e.target.value })} required className="h-9 text-sm" />
                  </div>
                </div>
                <div>
                  <Label htmlFor="m-email" className="text-xs">Email *</Label>
                  <Input id="m-email" type="email" value={formData.email || ""} onChange={(e) => setFormData({ ...formData, email: e.target.value })} required className="h-9 text-sm" />
                </div>
                <div>
                  <Label htmlFor="m-phone" className="text-xs">Phone Number</Label>
                  <Input id="m-phone" type="tel" placeholder="+48123456789" value={formData.phone_number || ""} onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })} className="h-9 text-sm" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Doctor Role *</Label>
                    <Select value={formData.role} onValueChange={(v) => setFormData({ ...formData, role: v as DoctorRole })}>
                      <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="resident">Resident</SelectItem>
                        <SelectItem value="specialist">Specialist</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs">User Role *</Label>
                    <Select value={(formData as any).user_role || "doctor"} onValueChange={(v) => setFormData({ ...formData, user_role: v as any } as any)}>
                      <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="doctor">Doctor</SelectItem>
                        <SelectItem value="doctor_admin">Doctor Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-2 border-t pt-2.5">
                  <Label className="text-xs font-semibold">Status</Label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={formData.is_active} onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })} className="h-4 w-4 rounded" />
                    <span className="text-sm">Active in Scheduling</span>
                  </label>
                  {editingDoctor && (
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={(formData as any).user_is_active !== false} onChange={(e) => setFormData({ ...formData, user_is_active: e.target.checked } as any)} className="h-4 w-4 rounded" />
                      <span className="text-sm">Can Login</span>
                    </label>
                  )}
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={formData.is_head} onChange={(e) => setFormData({ ...formData, is_head: e.target.checked })} className="h-4 w-4 rounded" />
                    <span className="text-sm">Head of Department</span>
                  </label>
                </div>
                <div className="flex gap-2 pt-3">
                  <Button type="submit" className="flex-1" size="sm">
                    {editingDoctor ? "Update" : "Create"}
                  </Button>
                  <Button type="button" variant="outline" className="flex-1" size="sm" onClick={() => { setIsModalOpen(false); setEditingDoctor(null); resetForm(); }}>
                    Cancel
                  </Button>
                </div>
              </form>
            </SheetContent>
          </Sheet>
        ) : (
          <Dialog open={isModalOpen} onOpenChange={(open) => {
            if (!open) { setIsModalOpen(false); setEditingDoctor(null); resetForm(); }
          }}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>{editingDoctor ? "Edit Doctor" : "Add New Doctor"}</DialogTitle>
                <DialogDescription>
                  {editingDoctor
                    ? `Editing ${editingDoctor.first_name} ${editingDoctor.last_name}`
                    : "Fill in the details to create a new doctor"}
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="first_name">First Name *</Label>
                    <Input id="first_name" value={formData.first_name} onChange={(e) => setFormData({ ...formData, first_name: e.target.value })} required />
                  </div>
                  <div>
                    <Label htmlFor="last_name">Last Name *</Label>
                    <Input id="last_name" value={formData.last_name} onChange={(e) => setFormData({ ...formData, last_name: e.target.value })} required />
                  </div>
                </div>
                <div>
                  <Label htmlFor="email">Email *</Label>
                  <Input id="email" type="email" value={formData.email || ""} onChange={(e) => setFormData({ ...formData, email: e.target.value })} required />
                </div>
                <div>
                  <Label htmlFor="phone_number">Phone Number</Label>
                  <Input id="phone_number" type="tel" placeholder="+48123456789" value={formData.phone_number || ""} onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })} />
                  <p className="text-xs text-muted-foreground mt-1">
                    For SMS notifications. Use E.164 format (e.g. +48123456789).
                  </p>
                </div>
                <div>
                  <Label>Doctor Role *</Label>
                  <Select value={formData.role} onValueChange={(v) => setFormData({ ...formData, role: v as DoctorRole })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="resident">Resident</SelectItem>
                      <SelectItem value="specialist">Specialist</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>User Role *</Label>
                  <Select value={(formData as any).user_role || "doctor"} onValueChange={(v) => setFormData({ ...formData, user_role: v as any } as any)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="doctor">Doctor</SelectItem>
                      <SelectItem value="doctor_admin">Doctor Admin</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    Doctor: can view schedules. Doctor Admin: can also manage preferences.
                  </p>
                </div>
                <div className="space-y-2 border-t pt-3">
                  <Label className="text-sm font-semibold">Status Settings</Label>
                  <div className="flex items-center space-x-2">
                    <input type="checkbox" id="is_active" checked={formData.is_active} onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })} className="h-4 w-4" />
                    <Label htmlFor="is_active" className="font-normal">Active in Scheduling</Label>
                  </div>
                  <p className="text-xs text-muted-foreground ml-6">Include this doctor in the scheduling algorithm</p>
                  {editingDoctor && (
                    <>
                      <div className="flex items-center space-x-2">
                        <input type="checkbox" id="user_is_active" checked={(formData as any).user_is_active !== false} onChange={(e) => setFormData({ ...formData, user_is_active: e.target.checked } as any)} className="h-4 w-4" />
                        <Label htmlFor="user_is_active" className="font-normal">Can Login</Label>
                      </div>
                      <p className="text-xs text-muted-foreground ml-6">Allow this user to log in to the system</p>
                    </>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  <input type="checkbox" id="is_head" checked={formData.is_head} onChange={(e) => setFormData({ ...formData, is_head: e.target.checked })} className="h-4 w-4" />
                  <Label htmlFor="is_head">Head of Department</Label>
                </div>
                <div className="flex space-x-2 pt-4">
                  <Button type="submit" className="flex-1">{editingDoctor ? "Update" : "Create"}</Button>
                  <Button type="button" variant="outline" className="flex-1" onClick={() => { setIsModalOpen(false); setEditingDoctor(null); resetForm(); }}>Cancel</Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
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
