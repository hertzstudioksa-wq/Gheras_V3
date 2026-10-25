import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, fileSrc } from "../lib/api";
import { orderPath } from "../lib/orderPath";
import { useAuth } from "../contexts/AuthContext";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import OrderStatusBadge from "../components/gheras/OrderStatusBadge";
import LoadError from "../components/gheras/LoadError";
import { Sprout, Plus, BookOpen, Calendar, PlayCircle } from "lucide-react";
import { usePageTitle } from "../lib/usePageTitle";

/** A stored image at card size (the server scales it down). */
function thumb(url, width = 640) {
  if (!url) return "";
  const src = fileSrc(url);
  return src.includes("/api/uploads/file/") ? `${src}&w=${width}` : src;
}

export default function Dashboard() {
  usePageTitle("قصصي");
  const { user } = useAuth();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    api.get("/orders")
      .then((r) => setOrders(r.data))
      .catch((e) => setError(errorMessage(e, "تعذّر تحميل قصصك، حاول مرة أخرى")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="user-dashboard">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 md:py-16">
        <div className="flex items-end justify-between mb-8 md:mb-10 flex-wrap gap-4">
          <div>
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              أهلاً، {user?.full_name} 🌱
            </h1>
            <p className="font-body text-[#5A677D]">هنا كل القصص التي صنعتها لأطفالك</p>
          </div>
          <Link to="/story/new" className="btn-primary inline-flex items-center gap-2" data-testid="dashboard-new-btn">
            <Plus className="w-5 h-5" /> قصة جديدة
          </Link>
        </div>

        {loading ? (
          <div className="text-center py-20 text-[#8A9AB0]">جارٍ التحميل...</div>
        ) : error ? (
          <LoadError message={error} onRetry={load} />
        ) : orders.length === 0 ? (
          <div className="bg-white rounded-[2rem] p-12 border border-[#E2D8C9] text-center" data-testid="empty-state">
            <div className="w-20 h-20 rounded-3xl bg-[#E8F0E1] grid place-content-center mx-auto mb-6">
              <Sprout className="w-10 h-10 text-[#729352]" />
            </div>
            <h2 className="font-heading text-2xl font-bold text-[#2D3748] mb-3">لم تبدأ أي قصة بعد</h2>
            <p className="font-body text-[#5A677D] mb-6 max-w-md mx-auto">
              ابدأ أول قصة مخصصة لطفلك واغرس قيمة جميلة في قلبه
            </p>
            <Link to="/story/new" className="btn-primary inline-flex items-center gap-2">
              <Sprout className="w-5 h-5" /> ابدأ الآن
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 md:gap-6" data-testid="orders-grid">
            {orders.map((o, i) => {
              const ready = ["delivered", "completed"].includes(o.status);
              return (
                <Link
                  key={o.id}
                  to={orderPath(o)}
                  className="bg-white rounded-3xl border border-[#E2D8C9] card-lift block overflow-hidden animate-grow"
                  style={{ animationDelay: `${i * 0.05}s` }}
                  data-testid={`order-card-${o.id}`}
                >
                  <div className="relative aspect-[3/2] bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7]">
                    {o.cover_url ? (
                      <img src={thumb(o.cover_url)} alt="" loading="lazy" className="absolute inset-0 w-full h-full object-cover" />
                    ) : (
                      <div className="absolute inset-0 grid place-content-center">
                        <BookOpen className="w-12 h-12 text-[#87A96B]/60" />
                      </div>
                    )}
                    {ready && o.cover_url && (
                      <span className="absolute inset-0 grid place-content-center bg-black/10">
                        <PlayCircle className="w-14 h-14 text-white drop-shadow-lg" />
                      </span>
                    )}
                    <span className="absolute top-3 right-3">
                      <OrderStatusBadge status={o.status} audience="parent" paused={o.engine_paused} />
                    </span>
                  </div>
                  <div className="p-5">
                    <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-1 line-clamp-2">
                      {o.title || `قصة ${o.child_name}`}
                    </h3>
                    <p className="font-body text-sm text-[#5A677D] mb-3">
                      {o.title ? `بطلها ${o.child_name}` : (o.category_name || "")}
                      {o.subcategory_name ? ` • ${o.subcategory_name}` : ""}
                    </p>
                    <div className="flex items-center gap-2 text-xs text-[#8A9AB0] font-body">
                      <Calendar className="w-3 h-3" />
                      {new Date(o.created_at).toLocaleDateString("ar-SA-u-ca-gregory", { day: "numeric", month: "long", year: "numeric" })}
                    </div>
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
