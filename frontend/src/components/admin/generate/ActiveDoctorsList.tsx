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
    <Card className="mb-4 sm:mb-6">
      <CardHeader className="px-4 py-3 sm:px-6 sm:py-4 flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base sm:text-lg font-semibold">
          Doctors ({doctors.length})
        </CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate("/admin/doctors")}
          className="h-7 text-xs sm:h-8 sm:text-sm"
        >
          <Pencil className="h-3.5 w-3.5 sm:h-4 sm:w-4 mr-1.5 sm:mr-2" />
          Edit
        </Button>
      </CardHeader>
      <CardContent className="px-4 sm:px-6 pb-4">
        {loading ? (
          <div className="text-center py-3 sm:py-4 text-xs sm:text-sm text-muted-foreground">
            Loading doctors...
          </div>
        ) : doctors.length === 0 ? (
          <div className="text-center py-3 sm:py-4 text-xs sm:text-sm text-muted-foreground">
            No active doctors found.
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5 sm:gap-2">
            {doctors.map((doctor) => (
              <div
                key={doctor.id}
                className="inline-flex items-center px-2 py-1 sm:px-3 sm:py-1.5 rounded-full bg-gray-100 text-xs sm:text-sm"
              >
                <span className="font-medium">
                  {doctor.first_name} {doctor.last_name}
                </span>
                <span
                  className={`ml-1.5 sm:ml-2 px-1 sm:px-1.5 py-0.5 text-[10px] sm:text-xs rounded ${
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
