import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "../../components/shared/Header";
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
      alert(successMsg);
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
      alert(errorMsg);
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
      <Header />
      <main className="container mx-auto px-4 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/admin/doctors")}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <h2 className="text-3xl font-bold">Pending Doctor Registrations</h2>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Pending Approvals ({pendingDoctors.length})</CardTitle>
            <CardDescription>
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
            ) : (
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
            )}
          </CardContent>
        </Card>

        {/* Approval Modal */}
        {isApprovalModalOpen && selectedDoctor && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <Card className="w-full max-w-md">
              <CardHeader>
                <CardTitle>Approve Registration</CardTitle>
                <CardDescription>
                  Set role and permissions for {selectedDoctor.first_name}{" "}
                  {selectedDoctor.last_name}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form className="space-y-4">
                  <div>
                    <Label htmlFor="role">Doctor Role *</Label>
                    <select
                      id="role"
                      value={approvalData.role}
                      onChange={(e) =>
                        setApprovalData({
                          ...approvalData,
                          role: e.target.value as any,
                        })
                      }
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="resident">Resident</option>
                      <option value="specialist">Specialist</option>
                    </select>
                  </div>

                  <div>
                    <Label htmlFor="user_role">User Role *</Label>
                    <select
                      id="user_role"
                      value={approvalData.user_role}
                      onChange={(e) =>
                        setApprovalData({
                          ...approvalData,
                          user_role: e.target.value as any,
                        })
                      }
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="doctor">Doctor</option>
                      <option value="doctor_admin">Doctor Admin</option>
                    </select>
                    <p className="text-xs text-muted-foreground mt-1">
                      Doctor: view only. Doctor Admin: can manage preferences.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="is_active"
                        checked={approvalData.is_active}
                        onChange={(e) =>
                          setApprovalData({
                            ...approvalData,
                            is_active: e.target.checked,
                          })
                        }
                        className="h-4 w-4"
                      />
                      <Label htmlFor="is_active">Active in Scheduling</Label>
                    </div>

                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="is_head"
                        checked={approvalData.is_head}
                        onChange={(e) =>
                          setApprovalData({
                            ...approvalData,
                            is_head: e.target.checked,
                          })
                        }
                        className="h-4 w-4"
                      />
                      <Label htmlFor="is_head">Head of Department</Label>
                    </div>
                  </div>

                  <div className="flex space-x-2 pt-4">
                    <Button
                      type="button"
                      onClick={handleApprove}
                      className="flex-1 bg-green-600 hover:bg-green-700"
                    >
                      Approve & Send Email
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="flex-1"
                      onClick={() => {
                        setIsApprovalModalOpen(false);
                        setSelectedDoctor(null);
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
      </main>
    </div>
  );
};
