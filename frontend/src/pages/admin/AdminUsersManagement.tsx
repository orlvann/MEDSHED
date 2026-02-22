import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
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
import { adminUsersApi } from "../../services/api";
import type { AdminUser, AdminUserCreate, AdminUserUpdate } from "../../types";
import {
  ArrowLeft,
  Plus,
  Pencil,
  Trash2,
  Search,
  AlertTriangle,
  UserCog,
} from "lucide-react";
import { useIsMobile } from "../../hooks/useMediaQuery";
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

export const AdminUsersManagement = () => {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Pagination and filters
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<"true" | "false" | "all">(
    "all"
  );

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [formData, setFormData] = useState<
    AdminUserCreate & { is_active?: boolean }
  >({
    email: "",
  });

  // Delete confirmation state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [userToDelete, setUserToDelete] = useState<AdminUser | null>(null);

  // Fetch users
  const fetchUsers = async () => {
    try {
      setLoading(true);
      const params = {
        page,
        size: 20,
        ...(search && { search }),
        is_active: activeFilter,
      };
      const response = await adminUsersApi.list(params);
      setUsers(response.items);
      setTotal(response.total);
      setError("");
    } catch (err: any) {
      setError("Failed to load admin users");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [page, search, activeFilter]);

  // Handle create/update
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingUser) {
        const updateData: AdminUserUpdate = {
          email:
            formData.email !== editingUser.email ? formData.email : undefined,
          is_active:
            formData.is_active !== editingUser.is_active
              ? formData.is_active
              : undefined,
        };
        await adminUsersApi.update(editingUser.id, updateData);
      } else {
        await adminUsersApi.create(formData);
      }
      setIsModalOpen(false);
      setEditingUser(null);
      resetForm();
      fetchUsers();
    } catch (err: any) {
      let errorMsg = "Failed to save admin user";
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
  const openDeleteDialog = (user: AdminUser) => {
    setUserToDelete(user);
    setDeleteDialogOpen(true);
  };

  // Handle delete confirmation
  const confirmDelete = async () => {
    if (!userToDelete) return;

    try {
      await adminUsersApi.delete(userToDelete.id);
      setDeleteDialogOpen(false);
      setUserToDelete(null);
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to delete admin user");
      setDeleteDialogOpen(false);
      setUserToDelete(null);
    }
  };

  const openCreateModal = () => {
    resetForm();
    setEditingUser(null);
    setIsModalOpen(true);
  };

  const openEditModal = (user: AdminUser) => {
    setFormData({
      email: user.email,
      is_active: user.is_active,
    });
    setEditingUser(user);
    setIsModalOpen(true);
  };

  const resetForm = () => {
    setFormData({
      email: "",
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
            <div>
              <h2 className="text-xl sm:text-3xl font-bold flex items-center gap-2">
                <UserCog className="h-5 w-5 sm:h-8 sm:w-8" />
                <span className="sm:hidden">Admin Users</span>
                <span className="hidden sm:inline">Manage Admin Users</span>
              </h2>
              <p className="text-xs sm:text-sm text-muted-foreground mt-0.5 sm:mt-1">
                Manage users with admin role
              </p>
            </div>
          </div>
          <Button size={isMobile ? "sm" : "default"} onClick={openCreateModal}>
            <Plus className="h-4 w-4 sm:mr-2" />
            <span className="hidden sm:inline">Add Admin User</span>
            <span className="sm:hidden">Add</span>
          </Button>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-4 sm:mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 sm:h-10 text-sm"
            />
          </div>
          <Select value={activeFilter} onValueChange={(v) => setActiveFilter(v as any)}>
            <SelectTrigger className="h-9 sm:h-10 w-[100px] sm:w-[120px] shrink-0"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="true">Active</SelectItem>
              <SelectItem value="false">Inactive</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Users Table */}
        <Card>
          <CardHeader className="px-4 py-3 sm:px-6 sm:py-6">
            <CardTitle className="text-base sm:text-xl">Admin Users ({total})</CardTitle>
            <CardDescription className="text-xs sm:text-sm">
              View and manage all admin users in the system
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-center py-8">Loading...</div>
            ) : error ? (
              <div className="text-center py-8 text-red-600">{error}</div>
            ) : users.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No admin users found
              </div>
            ) : isMobile ? (
                /* Mobile card view */
                <div className="space-y-2">
                  {users.map((user) => (
                    <div key={user.id} className="border rounded-lg p-2.5 hover:bg-muted/50">
                      <div className="flex items-start justify-between mb-1.5">
                        <div className="min-w-0 flex-1 mr-2">
                          <p className="text-sm font-medium truncate">{user.email}</p>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            Created: {new Date(user.created_at).toLocaleDateString()}
                          </p>
                        </div>
                        <div className="flex items-center gap-0.5 shrink-0">
                          <Button variant="ghost" size="icon" className="h-8 w-8 p-0" onClick={() => openEditModal(user)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 p-0"
                            onClick={() => openDeleteDialog(user)}
                            disabled={user.id === currentUser?.id}
                            title={user.id === currentUser?.id ? "You cannot delete your own account" : "Delete user"}
                          >
                            <Trash2 className={`h-3.5 w-3.5 ${user.id === currentUser?.id ? "text-gray-400" : "text-red-600"}`} />
                          </Button>
                        </div>
                      </div>
                      <span className={`px-1.5 py-0.5 text-[11px] rounded ${
                        user.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"
                      }`}>
                        {user.is_active ? "Active" : "Inactive"}
                      </span>
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
                        <th className="text-left py-3 px-4">Email</th>
                        <th className="text-left py-3 px-4">Status</th>
                        <th className="text-left py-3 px-4">Created</th>
                        <th className="text-right py-3 px-4">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((user) => (
                        <tr key={user.id} className="border-b hover:bg-muted/50">
                          <td className="py-3 px-4">{user.id}</td>
                          <td className="py-3 px-4 font-medium">{user.email}</td>
                          <td className="py-3 px-4">
                            <span
                              className={`px-2 py-1 text-xs rounded ${
                                user.is_active
                                  ? "bg-green-100 text-green-700"
                                  : "bg-gray-100 text-gray-700"
                              }`}
                            >
                              {user.is_active ? "Active" : "Inactive"}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-sm text-muted-foreground">
                            {new Date(user.created_at).toLocaleDateString()}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openEditModal(user)}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openDeleteDialog(user)}
                              disabled={user.id === currentUser?.id}
                              title={user.id === currentUser?.id ? "You cannot delete your own account" : "Delete user"}
                            >
                              <Trash2 className={`h-4 w-4 ${user.id === currentUser?.id ? "text-gray-400" : "text-red-600"}`} />
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }

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

        {/* Modal — Sheet on mobile, Dialog on desktop */}
        {isMobile ? (
          <Sheet open={isModalOpen} onOpenChange={(open) => {
            if (!open) { setIsModalOpen(false); setEditingUser(null); resetForm(); }
          }}>
            <SheetContent side="bottom" className="rounded-t-xl max-h-[85vh] overflow-y-auto px-4 pb-6">
              <SheetHeader className="mb-3">
                <SheetTitle>{editingUser ? "Edit Admin User" : "Add Admin User"}</SheetTitle>
                <SheetDescription>
                  {editingUser
                    ? `Editing ${editingUser.email}`
                    : "A password setup email will be sent to the user"}
                </SheetDescription>
              </SheetHeader>
              <form onSubmit={handleSubmit} className="space-y-3">
                <div>
                  <Label htmlFor="m-email" className="text-xs">Email *</Label>
                  <Input id="m-email" type="email" value={formData.email} onChange={(e) => setFormData({ ...formData, email: e.target.value })} required className="h-9 text-sm" />
                </div>
                {editingUser && (
                  <div className="space-y-1.5 border-t pt-2.5">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={formData.is_active !== false} onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })} disabled={editingUser.id === currentUser?.id} className="h-4 w-4 rounded" />
                      <span className="text-sm">Active (can login)</span>
                    </label>
                    {editingUser.id === currentUser?.id && (
                      <p className="text-xs text-amber-600 ml-6">You cannot deactivate your own account</p>
                    )}
                  </div>
                )}
                <div className="flex gap-2 pt-3">
                  <Button type="submit" className="flex-1" size="sm">{editingUser ? "Update" : "Create"}</Button>
                  <Button type="button" variant="outline" className="flex-1" size="sm" onClick={() => { setIsModalOpen(false); setEditingUser(null); resetForm(); }}>Cancel</Button>
                </div>
              </form>
            </SheetContent>
          </Sheet>
        ) : (
          <Dialog open={isModalOpen} onOpenChange={(open) => {
            if (!open) { setIsModalOpen(false); setEditingUser(null); resetForm(); }
          }}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>{editingUser ? "Edit Admin User" : "Add New Admin User"}</DialogTitle>
                {!editingUser && (
                  <DialogDescription>
                    A password setup email will be sent to the user
                  </DialogDescription>
                )}
              </DialogHeader>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <Label htmlFor="email">Email *</Label>
                  <Input id="email" type="email" value={formData.email} onChange={(e) => setFormData({ ...formData, email: e.target.value })} required />
                </div>
                {editingUser && (
                  <div>
                    <div className="flex items-center space-x-2">
                      <input type="checkbox" id="is_active" checked={formData.is_active !== false} onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })} disabled={editingUser.id === currentUser?.id} className="h-4 w-4" />
                      <Label htmlFor="is_active">Active (can login)</Label>
                    </div>
                    {editingUser.id === currentUser?.id && (
                      <p className="text-xs text-amber-600 mt-1">You cannot deactivate your own account</p>
                    )}
                  </div>
                )}
                <div className="flex space-x-2 pt-4">
                  <Button type="submit" className="flex-1">{editingUser ? "Update" : "Create"}</Button>
                  <Button type="button" variant="outline" className="flex-1" onClick={() => { setIsModalOpen(false); setEditingUser(null); resetForm(); }}>Cancel</Button>
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
                {userToDelete && (
                  <>
                    This will permanently delete admin user{" "}
                    <strong>{userToDelete.email}</strong>. This action cannot be
                    undone.
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
