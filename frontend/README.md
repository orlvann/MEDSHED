# MedShed Frontend

React + TypeScript + Vite frontend for the MedShed medical staff scheduling application.

## Tech Stack

- **React 18** - UI library
- **TypeScript 5** - Type safety
- **Vite 5** - Build tool and dev server
- **React Router 6** - Client-side routing
- **ShadCN/UI** - Component library (Radix UI + Tailwind CSS)
- **Axios** - HTTP client
- **Lucide React** - Icons

## Prerequisites

- **Node.js** 18+ and npm
- Backend API running on `http://127.0.0.1:8000` (see `../backend/`)

## Quick Start

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Environment Variables (Optional)

Create a `.env` file if you need to customize the API URL:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

By default, the app will connect to `http://127.0.0.1:8000`.

### 3. Run Development Server

```bash
npm run dev
```

The app will be available at `http://localhost:5173`.

### 4. Login Credentials (Development)

After running the backend seeding script (`make db-seed`), you can log in with:

**Admin:**

- Email: `admin@hospital.org`
- Password: `admin123`

**Doctor:**

- Email: `doctor@hospital.org`
- Password: `doctor123`

## Available Scripts

- `npm run dev` - Start development server (with hot reload)
- `npm run build` - Build for production
- `npm run preview` - Preview production build locally
- `npm run lint` - Run ESLint

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── ui/              # ShadCN UI components (Button, Input, Card, etc.)
│   │   └── shared/          # Shared components (Header, ProtectedRoute)
│   ├── contexts/
│   │   └── AuthContext.tsx  # Authentication context and state
│   ├── pages/
│   │   ├── auth/            # Login pages (Admin, Doctor)
│   │   └── admin/           # Admin pages (Home, DoctorsManagement)
│   ├── services/
│   │   └── api.ts           # API client (Axios instance + endpoints)
│   ├── types/
│   │   └── index.ts         # TypeScript type definitions
│   ├── lib/
│   │   └── utils.ts         # Utility functions
│   ├── App.tsx              # Main app component with routing
│   ├── main.tsx             # Entry point
│   └── index.css            # Global styles + Tailwind
├── package.json
├── vite.config.ts           # Vite configuration
├── tailwind.config.js       # Tailwind CSS configuration
└── tsconfig.json            # TypeScript configuration
```

## Features Implemented

### Authentication

- ✅ Separate login pages for Admin and Doctor
- ✅ JWT token-based authentication
- ✅ Protected routes with role-based access control
- ✅ Auth context for global state management

### Admin Features

- ✅ Admin dashboard with navigation cards
- ✅ Doctors CRUD management
  - List with pagination and filters
  - Create new doctor
  - Edit existing doctor
  - Delete doctor
  - Search by name/email
  - Filter by role and status

### UI Components (ShadCN/UI)

- ✅ Button
- ✅ Input
- ✅ Label
- ✅ Card
- ✅ Custom styling with Tailwind CSS

## API Integration

The frontend communicates with the backend API at `/api/v1`. Key endpoints:

- `POST /api/v1/auth/login` - User login
- `GET /api/v1/auth/me` - Get current user
- `GET /api/v1/doctors` - List doctors (with pagination and filters)
- `POST /api/v1/doctors` - Create doctor
- `PUT /api/v1/doctors/{id}` - Update doctor
- `DELETE /api/v1/doctors/{id}` - Delete doctor

## Development Notes

### CORS

The backend must have CORS enabled for the frontend origin. Set `ALLOWED_ORIGINS` in the backend `.env`:

```bash
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### API Proxy

Vite is configured to proxy `/api` requests to the backend during development. See `vite.config.ts`.

### Token Storage

JWT tokens are stored in `localStorage`. In production, consider using `httpOnly` cookies for better security.

## Troubleshooting

### Cannot connect to backend

- Ensure the backend is running on `http://127.0.0.1:8000`
- Check CORS configuration in backend `.env`
- Check browser console for errors

### Login fails

- Verify user exists in database (run `make db-seed` in backend)
- Check backend logs for authentication errors
- Ensure JWT_SECRET is set in backend `.env`

### Build errors

- Delete `node_modules` and reinstall: `rm -rf node_modules && npm install`
- Clear Vite cache: `rm -rf node_modules/.vite`

## License

See main project README.
