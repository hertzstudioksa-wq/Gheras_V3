import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import OrderStatusBadge from "../components/gheras/OrderStatusBadge";
import { Sprout, Plus, BookOpen, Calendar } from "lucide-react";

export default function Dashboard() {
  const { user } = useAuth();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/orders").then((r) => setOrders(r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="user-dashboard">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 md:py-16">
        <div className="flex items-end justify-between mb-10 flex-wrap gap-4">
          <div>
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              أهلاً، {user?.full_name} 🌱
            </h1>
            <p className="font-body text-[#5A677D]">هذه كل القصص التي بدأتها لطفلك</p>
          </div>
          <Link to="/story/new" className="btn-primary inline-flex items-center gap-2" data-testid="dashboard-new-btn">
            <Plus className="w-5 h-5" /> قصة جديدة
          </Link>
        </div>

        {loading ? (
          <div className="text-center py-20 text-[#8A9AB0]">جاري التحميل...</div>
        ) : orders.length === 0 ? (
          <div className="bg-white rounded-[2rem] p-12 border border-[#E2D8C9] text-center" data-testid="empty-state">
            <div className="w-20 h-20 rounded-3xl bg-[#E8F0E1] grid place-content-center mx-auto mb-6">
              <Sprout className="w-10 h-10 text-[#729352]" />
            </div>
            <h2 className="font-heading text-2xl font-bold text-[#2D3748] mb-3">لم تبدأ أي قصة بعد</h2>
            <p className="font-body text-[#5A677D] mb-6 max-w-md mx-auto">
              ابدأ أول قصة مخصصة لطفلك وغرس قيمة جميلة في قلبه
            </p>
            <Link to="/story/new" className="btn-primary inline-flex items-center gap-2">
              <Sprout className="w-5 h-5" /> ابدأ الآن
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" data-testid="orders-grid">
            {orders.map((o, i) => {
              const target =
                o.status === "scenarios_ready" || o.status === "scenarios_generating"
                  ? `/orders/${o.id}/scenarios`
                  : ["production_ready", "production_planning", "production_approved", "ready_for_ai"].includes(o.status)
                  ? `/orders/${o.id}/production-ready`
                  : `/orders/${o.id}`;
              return (
              <Link
                key={o.id}
                to={target}
                className="bg-white rounded-3xl p-6 border border-[#E2D8C9] card-lift block animate-grow"
                style={{ animationDelay: `${i * 0.05}s` }}
                data-testid={`order-card-${o.id}`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="w-12 h-12 rounded-2xl bg-[#E8F0E1] grid place-content-center">
                    <BookOpen className="w-6 h-6 text-[#729352]" />
                  </div>
                  <OrderStatusBadge status={o.status} />
                </div>
                <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-1">قصة {o.child_name}</h3>
                <p className="font-body text-sm text-[#5A677D] mb-4">
                  {o.category_name}
                  {o.subcategory_name ? ` • ${o.subcategory_name}` : ""}
                </p>
                <div className="flex items-center gap-2 text-xs text-[#8A9AB0] font-body">
                  <Calendar className="w-3 h-3" />
                  {new Date(o.created_at).toLocaleDateString("ar-EG")}
                </div>
              </Link>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
