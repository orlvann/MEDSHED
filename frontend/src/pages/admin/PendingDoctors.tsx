import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AdminHeader } from "../../components/shared/AdminHeader";
import { Button } from "../../components/ui/button";
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
import axios from "axios";
import { ArrowLeft, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
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

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

interface PendingDoctor {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  created_at: string;
}

export const PendingDoctors = () => {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [pendingDoctors, setPendingDoctors] = useState<PendingDoctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Approval modal state
  const [isApprovalModalOpen, setIsApprovalModalOpen] = useState(false);
  const [selectedDoctor, setSelectedDoctor] = useState<PendingDoctor | null>(
    null
  );
  const [approvalData, setApprovalData] = useState({
    role: "resident",
    user_role: "doctor",
    is_head: false,
    is_active: true,
  });

  // Rejection dialog state
  const [isRejectDialogOpen, setIsRejectDialogOpen] = useState(false);
  const [doctorToReject, setDoctorToReject] = useState<PendingDoctor | null>(
    null
  );

  // Result dialog state (replaces alert())
  const [resultDialogOpen, setResultDialogOpen] = useState(false);
  const [resultMessage, setResultMessage] = useState("");
  const [resultIsError, setResultIsError] = useState(false);

  const fetchPendingDoctors = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem("access_token");
      const response = await axios.get(
        `${API_BASE_URL}/api/v1/admin/pending-doctors?page=1&size=100`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      setPendingDoctors(response.data.items);
      setError("");
    } catch (err: any) {
      setError("Failed to load pending doctors");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPendingDoctors();
  }, []);

  const openApprovalModal = (doctor: PendingDoctor) => {
    setSelectedDoctor(doctor);
    setApprovalData({
      role: "resident",
      user_role: "doctor",
      is_head: false,
      is_active: true,
    });
    setIsApprovalModalOpen(true);
  };

  const handleApprove = async () => {
    if (!selectedDoctor) return;

    try {
      const token = localStorage.getItem("access_token");
      await axios.post(
        `${API_BASE_URL}/api/v1/admin/pending-doctors/${selectedDoctor.id}/approve`,
        approvalData,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      setIsApprovalModalOpen(false);
      setSelectedDoctor(null);
      await fetchPendingDoctors();

      // Show success message
      const successMsg = `Doctor ${selectedDoctor.first_name} ${selectedDoctor.last_name} approved successfully! Welcome email sent.`;
      setResultMessage(successMsg);
      setResultIsError(false);
      setResultDialogOpen(true);
    } catch (err: any) {
      let errorMsg = "Failed to approve doctor";
      if (err.response?.data?.detail) {
        if (typeof err.response.data.detail === "string") {
          errorMsg = err.response.data.detail;
        } else if (err.response.data.detail.detail) {
          errorMsg = err.response.data.detail.detail;
        } else {
          // If detail is an object, stringify it
          errorMsg = JSON.stringify(err.response.data.detail);
        }
      } else if (err.message) {
        errorMsg = err.message;
      }
      setResultMessage(errorMsg);
      setResultIsError(true);
      setResultDialogOpen(true);
    }
  };

  const openRejectDialog = (doctor: PendingDoctor) => {
    setDoctorToReject(doctor);
    setIsRejectDialogOpen(true);
  };

  const handleReject = async () => {
    if (!doctorToReject) return;

    try {
      const token = localStorage.getItem("access_token");
      await axios.delete(
        `${API_BASE_URL}/api/v1/admin/pending-doctors/${doctorToReject.id}/reject`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      setIsRejectDialogOpen(false);
      setDoctorToReject(null);
      fetchPendingDoctors();
    } catch (err: any) {
      setError("Failed to reject registration");
      setIsRejectDialogOpen(false);
    }
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
              onClick={() => navigate("/admin/doctors")}
              title="Back"
            >
              <ArrowLeft className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Back</span>
            </Button>
            <h2 className="text-xl sm:text-3xl font-bold">Pending Registrations</h2>
          </div>
        </div>

        <Card>
          <CardHeader className="px-4 py-3 sm:px-6 sm:py-6">
            <CardTitle className="text-base sm:text-xl">Pending Approvals ({pendingDoctors.length})</CardTitle>
            <CardDescription className="text-xs sm:text-sm">
              Review and approve or reject doctor registration requests
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-center py-8">Loading...</div>
            ) : error ? (
              <div className="text-center py-8 text-red-600">{error}</div>
            ) : pendingDoctors.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No pending registrations
              </div>
            ) : isMobile ? (
                /* Mobile card view */
                <div className="space-y-2">
                  {pendingDoctors.map((doctor) => (
                    <div key={doctor.id} className="border rounded-lg p-2.5">
                      <div className="flex items-start justify-between mb-1.5">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate">
                            {doctor.first_name} {doctor.last_name}
                          </p>
                          <p className="text-xs text-muted-foreground truncate">{doctor.email}</p>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            {new Date(doctor.created_at).toLocaleDateString()}
                          </p>
                        </div>
                      </div>
                      <div className="flex gap-2 mt-1.5">
                        <Button
                          size="sm"
                          onClick={() => openApprovalModal(doctor)}
                          className="flex-1 h-8 text-xs bg-green-600 hover:bg-green-700 text-white"
                        >
                          <CheckCircle className="h-3.5 w-3.5 mr-1" />
                          Approve
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openRejectDialog(doctor)}
                          className="flex-1 h-8 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                        >
                          <XCircle className="h-3.5 w-3.5 mr-1" />
                          Reject
                        </Button>
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
                        <th className="text-left py-3 px-4">First Name</th>
                        <th className="text-left py-3 px-4">Last Name</th>
                        <th className="text-left py-3 px-4">Email</th>
                        <th className="text-left py-3 px-4">Date Submitted</th>
                        <th className="text-right py-3 px-4">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pendingDoctors.map((doctor) => (
                        <tr
                          key={doctor.id}
                          className="border-b hover:bg-muted/50"
                        >
                          <td className="py-3 px-4">{doctor.first_name}</td>
                          <td className="py-3 px-4">{doctor.last_name}</td>
                          <td className="py-3 px-4 text-sm">{doctor.email}</td>
                          <td className="py-3 px-4 text-sm text-muted-foreground">
                            {new Date(doctor.created_at).toLocaleDateString()}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openApprovalModal(doctor)}
                              className="text-green-600 hover:text-green-700 hover:bg-green-50"
                            >
                              <CheckCircle className="h-4 w-4 mr-1" />
                              Approve
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openRejectDialog(doctor)}
                              className="text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                              <XCircle className="h-4 w-4 mr-1" />
                              Reject
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </CardContent>
        </Card>

        {/* Approval Modal — Sheet on mobile, Dialog on desktop */}
        {isMobile ? (
          <Sheet open={isApprovalModalOpen && !!selectedDoctor} onOpenChange={(open) => {
            if (!open) { setIsApprovalModalOpen(false); setSelectedDoctor(null); }
          }}>
            <SheetContent side="bottom" className="rounded-t-xl max-h-[85vh] overflow-y-auto px-4 pb-6">
              <SheetHeader className="mb-3">
                <SheetTitle>Approve Registration</SheetTitle>
                <SheetDescription>
                  {selectedDoctor && `Set role for ${selectedDoctor.first_name} ${selectedDoctor.last_name}`}
                </SheetDescription>
              </SheetHeader>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Doctor Role *</Label>
                    <Select value={approvalData.role} onValueChange={(value) => setApprovalData({ ...approvalData, role: value as any })}>
                      <SelectTrigger className="h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="resident">Resident</SelectItem>
                        <SelectItem value="specialist">Specialist</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs">User Role *</Label>
                    <Select value={approvalData.user_role} onValueChange={(value) => setApprovalData({ ...approvalData, user_role: value as any })}>
                      <SelectTrigger className="h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="doctor">Doctor</SelectItem>
                        <SelectItem value="doctor_admin">Doctor Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-2 border-t pt-2.5">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={approvalData.is_active} onChange={(e) => setApprovalData({ ...approvalData, is_active: e.target.checked })} className="h-4 w-4 rounded" />
                    <span className="text-sm">Active in Scheduling</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={approvalData.is_head} onChange={(e) => setApprovalData({ ...approvalData, is_head: e.target.checked })} className="h-4 w-4 rounded" />
                    <span className="text-sm">Head of Department</span>
                  </label>
                </div>
                <div className="flex gap-2 pt-3">
                  <Button type="button" size="sm" onClick={handleApprove} className="flex-1 bg-green-600 hover:bg-green-700">
                    Approve & Send Email
                  </Button>
                  <Button type="button" variant="outline" size="sm" className="flex-1" onClick={() => { setIsApprovalModalOpen(false); setSelectedDoctor(null); }}>
                    Cancel
                  </Button>
                </div>
              </div>
            </SheetContent>
          </Sheet>
        ) : (
          <Dialog open={isApprovalModalOpen && !!selectedDoctor} onOpenChange={(open) => {
            if (!open) { setIsApprovalModalOpen(false); setSelectedDoctor(null); }
          }}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>Approve Registration</DialogTitle>
                <DialogDescription>
                  {selectedDoctor && `Set role and permissions for ${selectedDoctor.first_name} ${selectedDoctor.last_name}`}
                </DialogDescription>
              </DialogHeader>
              <form className="space-y-4">
                <div>
                  <Label>Doctor Role *</Label>
                  <Select value={approvalData.role} onValueChange={(value) => setApprovalData({ ...approvalData, role: value as any })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="resident">Resident</SelectItem>
                      <SelectItem value="specialist">Specialist</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>User Role *</Label>
                  <Select value={approvalData.user_role} onValueChange={(value) => setApprovalData({ ...approvalData, user_role: value as any })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="doctor">Doctor</SelectItem>
                      <SelectItem value="doctor_admin">Doctor Admin</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    Doctor: view only. Doctor Admin: can manage preferences.
                  </p>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <input type="checkbox" id="is_active" checked={approvalData.is_active} onChange={(e) => setApprovalData({ ...approvalData, is_active: e.target.checked })} className="h-4 w-4" />
                    <Label htmlFor="is_active">Active in Scheduling</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <input type="checkbox" id="is_head" checked={approvalData.is_head} onChange={(e) => setApprovalData({ ...approvalData, is_head: e.target.checked })} className="h-4 w-4" />
                    <Label htmlFor="is_head">Head of Department</Label>
                  </div>
                </div>
                <div className="flex space-x-2 pt-4">
                  <Button type="button" onClick={handleApprove} className="flex-1 bg-green-600 hover:bg-green-700">
                    Approve & Send Email
                  </Button>
                  <Button type="button" variant="outline" className="flex-1" onClick={() => { setIsApprovalModalOpen(false); setSelectedDoctor(null); }}>
                    Cancel
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        )}

        {/* Reject Dialog */}
        <AlertDialog
          open={isRejectDialogOpen}
          onOpenChange={setIsRejectDialogOpen}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <div className="flex items-center space-x-2">
                <AlertTriangle className="h-5 w-5 text-red-600" />
                <AlertDialogTitle>Reject Registration?</AlertDialogTitle>
              </div>
              <AlertDialogDescription>
                {doctorToReject && (
                  <>
                    Are you sure you want to reject the registration for{" "}
                    <strong>
                      {doctorToReject.first_name} {doctorToReject.last_name}
                    </strong>{" "}
                    ({doctorToReject.email})?
                    <br />
                    <br />
                    This action cannot be undone. No email will be sent.
                  </>
                )}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleReject}
                className="bg-red-600 hover:bg-red-700"
              >
                Reject Registration
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Result Dialog (success/error) */}
        <AlertDialog open={resultDialogOpen} onOpenChange={setResultDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <div className="flex items-center space-x-2">
                {resultIsError ? (
                  <AlertTriangle className="h-5 w-5 text-red-600" />
                ) : (
                  <CheckCircle className="h-5 w-5 text-green-600" />
                )}
                <AlertDialogTitle>
                  {resultIsError ? "Error" : "Success"}
                </AlertDialogTitle>
              </div>
              <AlertDialogDescription>{resultMessage}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogAction>OK</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </main>
    </div>
  );
};
