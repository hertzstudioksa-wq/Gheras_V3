import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import OrderStatusBadge from "../components/gheras/OrderStatusBadge";
import { ArrowRight, User, Sprout, BookOpen, Sparkles, Calendar } from "lucide-react";

export default function OrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/orders/${id}`).then((r) => setOrder(r.data)).finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FDFBF7]">
        <Navbar />
        <div className="text-center py-40 text-[#8A9AB0]">جاري التحميل...</div>
      </div>
    );
  }
  if (!order) {
    return (
      <div className="min-h-screen bg-[#FDFBF7]">
        <Navbar />
        <div className="text-center py-40">
          <p className="text-[#5A677D] mb-4">الطلب غير موجود</p>
          <Link to="/dashboard" className="btn-primary inline-flex items-center gap-2">
            العودة إلى قصصي
          </Link>
        </div>
      </div>
    );
  }

  const child = order.child_snapshot || {};
  const personalization = order.personalization || {};

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="order-detail">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 md:py-16">
        <Link to="/dashboard" className="inline-flex items-center gap-2 text-[#5A677D] hover:text-[#2D3748] mb-6 font-body">
          <ArrowRight className="w-4 h-4" /> العودة إلى قصصي
        </Link>

        <div className="bg-white rounded-[2rem] p-8 md:p-10 border border-[#E2D8C9] mb-6">
          <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
            <div>
              <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
                قصة {child.name}
              </h1>
              <div className="flex items-center gap-2 text-sm text-[#8A9AB0] font-body">
                <Calendar className="w-3 h-3" />
                {new Date(order.created_at).toLocaleDateString("ar-EG")}
              </div>
            </div>
            <OrderStatusBadge status={order.status} />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <Row icon={<Sprout />} label="التصنيف" value={order.category_name} />
            {order.subcategory_name && <Row icon={<Sprout />} label="الموضوع" value={order.subcategory_name} />}
            {order.custom_goal && <Row icon={<Sprout />} label="الهدف المخصص" value={order.custom_goal} />}
            <Row icon={<User />} label="اسم الطفل" value={child.name} />
            <Row icon={<User />} label="العمر" value={`${child.age} سنة`} />
            <Row icon={<User />} label="الجنس" value={child.gender === "male" ? "ولد" : "بنت"} />
            {child.personality && <Row icon={<Sparkles />} label="الشخصية" value={child.personality} />}
            {child.interests && <Row icon={<Sparkles />} label="الاهتمامات" value={child.interests} />}
            <Row icon={<BookOpen />} label="الأسلوب" value={order.style_name} />
          </div>

          {personalization?.parent_message && (
            <div className="mt-6 bg-[#E8F0E1] rounded-2xl p-5 border border-[#87A96B]/30">
              <div className="font-body text-sm text-[#4F6B3B] font-bold mb-1">رسالة من الأهل</div>
              <p className="font-body text-[#2D3748]">{personalization.parent_message}</p>
            </div>
          )}

          {order.admin_note && (
            <div className="mt-6 bg-[#F8F1E7] rounded-2xl p-5 border border-[#D4A373]/30">
              <div className="font-body text-sm text-[#8B5A2B] font-bold mb-1">ملاحظة الفريق</div>
              <p className="font-body text-[#2D3748]">{order.admin_note}</p>
            </div>
          )}
        </div>

        <div className="bg-gradient-to-br from-[#E8F0E1] to-[#F8F1E7] rounded-[2rem] p-8 md:p-10 border border-[#E2D8C9] text-center">
          <Sprout className="w-12 h-12 text-[#729352] mx-auto mb-3" />
          <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2">
            القصة قيد التحضير
          </h3>
          <p className="font-body text-[#5A677D] max-w-lg mx-auto">
            فريقنا يُحضّر قصة طفلك بعناية. ستصلك عند الاكتمال، وتجدها هنا مع فيديو و PDF جاهز للمشاركة.
          </p>
        </div>
      </div>
      <Footer />
    </div>
  );
}

function Row({ icon, label, value }) {
  return (
    <div className="flex items-start gap-3 bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9]">
      <div className="w-9 h-9 rounded-xl bg-white border border-[#E2D8C9] grid place-content-center text-[#729352] shrink-0">
        {React.cloneElement(icon, { className: "w-4 h-4" })}
      </div>
      <div>
        <div className="font-body text-xs text-[#8A9AB0]">{label}</div>
        <div className="font-body font-bold text-[#2D3748]">{value}</div>
      </div>
    </div>
  );
}
