import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { Users, BookOpen, Clock, CheckCircle2, Sprout } from "lucide-react";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";

export default function AdminOverview() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/admin/stats").then((r) => setStats(r.data));
  }, []);

  if (!stats) return <div className="text-[#8A9AB0]">جاري التحميل...</div>;

  const cards = [
    { label: "المستخدمين", value: stats.users_count, icon: Users, color: "#87A96B" },
    { label: "إجمالي الطلبات", value: stats.orders_count, icon: BookOpen, color: "#D4A373" },
    { label: "بانتظار المراجعة", value: stats.pending_count, icon: Clock, color: "#E07A5F" },
    { label: "مكتملة", value: stats.completed_count, icon: CheckCircle2, color: "#4F6B3B" },
  ];

  return (
    <div data-testid="admin-overview">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">نظرة عامة</h1>
      <p className="font-body text-[#5A677D] mb-8">ملخص نشاط منصة غِراس</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
        {cards.map((c, i) => (
          <div key={i} className="bg-white rounded-3xl p-6 border border-[#E2D8C9]" data-testid={`stat-card-${i}`}>
            <div
              className="w-12 h-12 rounded-2xl grid place-content-center mb-4"
              style={{ backgroundColor: `${c.color}20` }}
            >
              <c.icon className="w-6 h-6" style={{ color: c.color }} />
            </div>
            <div className="font-heading text-3xl font-bold text-[#2D3748]">{c.value}</div>
            <div className="font-body text-sm text-[#8A9AB0]">{c.label}</div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-3xl p-6 md:p-8 border border-[#E2D8C9]">
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">أحدث الطلبات</h2>
          <Link to="/admin/orders" className="text-[#729352] font-bold text-sm">عرض الكل</Link>
        </div>
        {stats.recent_orders.length === 0 ? (
          <p className="text-[#8A9AB0] py-8 text-center">لا توجد طلبات بعد</p>
        ) : (
          <div className="space-y-3">
            {stats.recent_orders.map((o) => (
              <Link
                key={o.id}
                to={`/admin/orders`}
                className="flex items-center justify-between bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9] hover:bg-[#F8F1E7]"
              >
                <div className="flex items-center gap-3">
                  <Sprout className="w-5 h-5 text-[#729352]" />
                  <div>
                    <div className="font-body font-bold text-[#2D3748]">
                      قصة {o.child_snapshot?.name}
                    </div>
                    <div className="font-body text-xs text-[#8A9AB0]">
                      {new Date(o.created_at).toLocaleDateString("ar-EG")}
                    </div>
                  </div>
                </div>
                <OrderStatusBadge status={o.status} />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
