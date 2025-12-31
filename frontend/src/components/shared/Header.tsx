import { useState } from "react";
import { Calendar, User } from "lucide-react";
import { Button } from "../ui/button";
import { ProfileModal } from "./ProfileModal";

export const Header = () => {
  const [profileOpen, setProfileOpen] = useState(false);

  return (
    <>
      <header className="border-b bg-white shadow-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Calendar className="h-6 w-6 text-primary" />
            <h1 className="text-xl font-bold">MedShed</h1>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setProfileOpen(true)}
            className="h-9 w-9 p-0 rounded-full bg-gray-100 hover:bg-gray-200"
          >
            <User className="h-5 w-5 text-gray-600" />
          </Button>
        </div>
      </header>
      <ProfileModal open={profileOpen} onOpenChange={setProfileOpen} />
    </>
  );
};
