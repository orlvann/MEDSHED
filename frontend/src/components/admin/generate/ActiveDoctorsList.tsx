import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Button } from "../../ui/button";
import { Pencil } from "lucide-react";
import type { Doctor } from "../../../types";

interface ActiveDoctorsListProps {
  doctors: Doctor[];
  loading?: boolean;
}

export const ActiveDoctorsList = ({
  doctors,
  loading = false,
}: ActiveDoctorsListProps) => {
  const navigate = useNavigate();

  return (
    <Card className="mb-6">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle className="text-lg font-semibold">
          Participating Doctors ({doctors.length})
        </CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate("/admin/doctors")}
        >
          <Pencil className="h-4 w-4 mr-2" />
          Edit
        </Button>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="text-center py-4 text-muted-foreground">
            Loading doctors...
          </div>
        ) : doctors.length === 0 ? (
          <div className="text-center py-4 text-muted-foreground">
            No active doctors found. Please add doctors to the schedule.
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {doctors.map((doctor) => (
              <div
                key={doctor.id}
                className="inline-flex items-center px-3 py-1.5 rounded-full bg-gray-100 text-sm"
              >
                <span className="font-medium">
                  {doctor.first_name} {doctor.last_name}
                </span>
                <span
                  className={`ml-2 px-1.5 py-0.5 text-xs rounded ${
                    doctor.role === "specialist"
                      ? "bg-blue-100 text-blue-700"
                      : "bg-green-100 text-green-700"
                  }`}
                >
                  {doctor.role === "specialist" ? "S" : "R"}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
