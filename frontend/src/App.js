import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";

import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";

import Landing from "./pages/Landing";
import HowItWorks from "./pages/HowItWorks";
import Categories from "./pages/Categories";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import StoryBuilder from "./pages/StoryBuilder";
import Dashboard from "./pages/Dashboard";
import OrderDetail from "./pages/OrderDetail";
import ScenarioSelection from "./pages/ScenarioSelection";
import ProductionReady from "./pages/ProductionReady";

import AdminLayout from "./pages/admin/AdminLayout";
import AdminOverview from "./pages/admin/AdminOverview";
import AdminOrders from "./pages/admin/AdminOrders";
import AdminStoryboard from "./pages/admin/AdminStoryboard";
import AdminUsers from "./pages/admin/AdminUsers";
import AdminCategories from "./pages/admin/AdminCategories";
import AdminStoryOptions from "./pages/admin/AdminStoryOptions";
import AdminContent from "./pages/admin/AdminContent";
import AdminPrompts from "./pages/admin/AdminPrompts";
import AdminModels from "./pages/admin/AdminModels";
import AdminPipeline from "./pages/admin/AdminPipeline";
import AdminApiStatus from "./pages/admin/AdminApiStatus";
import AdminPlans from "./pages/admin/AdminPlans";
import AdminPricing from "./pages/admin/AdminPricing";
import AdminStageLab from "./pages/admin/AdminStageLab";
import AdminSecrets from "./pages/admin/AdminSecrets";
import AdminSettings from "./pages/admin/AdminSettings";

function App() {
  return (
    <div className="App" dir="rtl">
      <AuthProvider>
        <BrowserRouter>
          <Toaster
            position="top-center"
            dir="rtl"
            toastOptions={{
              style: {
                fontFamily: "'Tajawal', sans-serif",
                borderRadius: "1rem",
                border: "1px solid #E2D8C9",
              },
            }}
          />
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/how-it-works" element={<HowItWorks />} />
            <Route path="/categories" element={<Categories />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/story/new" element={<StoryBuilder />} />

            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <Dashboard />
                </ProtectedRoute>
              }
            />
            <Route
              path="/orders/:id"
              element={
                <ProtectedRoute>
                  <OrderDetail />
                </ProtectedRoute>
              }
            />
            <Route
              path="/orders/:id/scenarios"
              element={
                <ProtectedRoute>
                  <ScenarioSelection />
                </ProtectedRoute>
              }
            />
            <Route
              path="/orders/:id/production-ready"
              element={
                <ProtectedRoute>
                  <ProductionReady />
                </ProtectedRoute>
              }
            />

            <Route
              path="/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<AdminOverview />} />
              <Route path="orders" element={<AdminOrders />} />
              <Route path="orders/:orderId/storyboard" element={<AdminStoryboard />} />
              <Route path="users" element={<AdminUsers />} />
              <Route path="categories" element={<AdminCategories />} />
              <Route path="styles" element={<AdminStoryOptions />} />
              <Route path="content" element={<AdminContent />} />
              <Route path="prompts" element={<AdminPrompts />} />
              <Route path="models" element={<AdminModels />} />
              <Route path="pipeline" element={<AdminPipeline />} />
              <Route path="api-status" element={<AdminApiStatus />} />
              <Route path="plans" element={<AdminPlans />} />
              <Route path="pricing" element={<AdminPricing />} />
              <Route path="lab" element={<AdminStageLab />} />
              <Route path="secrets" element={<AdminSecrets />} />
              <Route path="settings" element={<AdminSettings />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
