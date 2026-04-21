import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileSrc } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import OrderStatusBadge from "../components/gheras/OrderStatusBadge";
import { ArrowRight, Sprout, Calendar, FileText, Image as ImageIcon, Award, ArrowLeft, Heart, BookOpen, Rocket, CheckCircle2 } from "lucide-react";

const ANGLE_META = {
  emotional:   { label: "عاطفي", icon: Heart, fg: "text-[#B8612F]", bg: "bg-[#FCE6D4]" },
  educational: { label: "تعليمي هادئ", icon: BookOpen, fg: "text-[#4F6B3B]", bg: "bg-[#E8F0E1]" },
  adventure:   { label: "مغامرة", icon: Rocket, fg: "text-[#8B5A2B]", bg: "bg-[#F8F1E7]" },
};

export default function OrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/orders/${id}`).then((r) => setOrder(r.data)).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="min-h-screen bg-[#FDFBF7]"><Navbar /><div className="text-center py-40 text-[#8A9AB0]">جاري التحميل...</div></div>;
  if (!order) return (
    <div className="min-h-screen bg-[#FDFBF7]"><Navbar />
      <div className="text-center py-40">
        <p className="text-[#5A677D] mb-4">الطلب غير موجود</p>
        <Link to="/dashboard" className="btn-primary">العودة إلى قصصي</Link>
      </div>
    </div>
  );

  const d = order.data || {};
  const child = d.child || {};
  const goal = d.goal || {};
  const pers = d.personalization || {};
  const e = order.enriched || {};

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="order-detail">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 md:py-16">
        <Link to="/dashboard" className="inline-flex items-center gap-2 text-[#5A677D] hover:text-[#2D3748] mb-6 font-body">
          <ArrowRight className="w-4 h-4" /> العودة إلى قصصي
        </Link>

        <div className="bg-white rounded-[2rem] p-6 md:p-10 border border-[#E2D8C9] mb-6">
          <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
            <div className="flex items-center gap-4">
              {child.image_url && (
                <img src={fileSrc(child.image_url)} alt={child.name} className="w-20 h-20 rounded-2xl object-cover border border-[#E2D8C9]" />
              )}
              <div>
                <h1 className="font-heading text-3xl font-bold text-[#2D3748]">قصة {child.name}</h1>
                <div className="flex items-center gap-2 text-sm text-[#8A9AB0] font-body">
                  <Calendar className="w-3 h-3" />
                  {new Date(order.created_at).toLocaleDateString("ar-EG")}
                </div>
              </div>
            </div>
            <OrderStatusBadge status={order.status} />
          </div>

          <div className="grid md:grid-cols-2 gap-3 mb-5">
            <Info label="التصنيف" value={e.category_name || "—"} />
            <Info label="الموضوع" value={e.subcategory_name || goal.custom_subcategory || "—"} />
            <Info label="العمر" value={`${child.age} سنة`} />
            <Info label="الجنس" value={child.gender === "male" ? "ولد" : "بنت" + (child.hijab ? " (حجاب)" : "")} />
            <Info label="نوع القصة" value={e.type_name || "—"} />
            <Info label="النبرة" value={e.tone_name || "—"} />
            <Info label="البيئة" value={e.setting_name || "—"} />
            <Info label="اللغة" value={e.language_name || "—"} />
          </div>

          {goal.context && (
            <div className="bg-[#E8F0E1] rounded-2xl p-5 border border-[#87A96B]/30 mb-4">
              <div className="font-body text-sm font-bold text-[#4F6B3B] mb-1">الموقف الحقيقي</div>
              <p className="font-body text-[#2D3748] whitespace-pre-wrap">{goal.context}</p>
            </div>
          )}

          {(d.characters || []).length > 0 && (
            <div className="mb-4">
              <h3 className="font-heading font-bold text-[#2D3748] mb-2">الشخصيات</h3>
              <div className="flex flex-wrap gap-3">
                {d.characters.map((c, i) => (
                  <div key={i} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] flex items-center gap-3">
                    {c.image_url && <img src={fileSrc(c.image_url)} alt="" className="w-10 h-10 rounded-xl object-cover" />}
                    <div>
                      <div className="font-body font-bold text-sm text-[#2D3748]">{c.type}{c.name ? ` — ${c.name}` : ""}</div>
                      <div className="font-body text-xs text-[#8A9AB0]">{c.role === "visible" ? "ظاهر في القصة" : "مذكور فقط"}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {pers.custom_notes && (
            <div className="bg-[#F8F1E7] rounded-2xl p-4 border border-[#D4A373]/30 mb-4">
              <div className="font-body text-xs font-bold text-[#8B5A2B] mb-1">تفاصيل خاصة</div>
              <p className="font-body text-[#2D3748]">{pers.custom_notes}</p>
            </div>
          )}

          {order.admin_note && (
            <div className="bg-[#FCE6D4] rounded-2xl p-4 border border-[#E07A5F]/30 mb-4">
              <div className="font-body text-xs font-bold text-[#B8612F] mb-1">ملاحظة الفريق</div>
              <p className="font-body text-[#2D3748]">{order.admin_note}</p>
            </div>
          )}
        </div>

        <div className="bg-gradient-to-br from-[#E8F0E1] to-[#F8F1E7] rounded-[2rem] p-8 md:p-10 border border-[#E2D8C9] text-center">
          <Sprout className="w-12 h-12 text-[#729352] mx-auto mb-3" />
          <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2">
            {order.status === "completed" ? "القصة جاهزة 🎉"
            : order.selected_scenario_snapshot ? "السيناريو مختار وجاهز للتوليد"
            : ["scenarios_generating","scenarios_ready"].includes(order.status) ? "اختر سيناريو القصة"
            : "القصة قيد التحضير"}
          </h3>
          <p className="font-body text-[#5A677D] max-w-lg mx-auto mb-4">
            {order.status === "completed" ? "يمكنك تحميل الفيديو و PDF أو مشاركة القصة"
            : ["scenarios_generating","scenarios_ready"].includes(order.status) ? "اضغط لاختيار السيناريو الذي يناسب طفلك"
            : "فريقنا يُحضّر قصة طفلك بعناية. ستصلك عند الاكتمال."}
          </p>
          {["scenarios_generating","scenarios_ready"].includes(order.status) && (
            <Link to={`/orders/${order.id}/scenarios`} className="btn-primary inline-flex items-center gap-2">
              <Sprout className="w-4 h-4" /> اذهب لاختيار السيناريو
            </Link>
          )}
        </div>

        {order.selected_scenario_snapshot && (
          <div className="bg-white rounded-[2rem] p-6 md:p-8 border border-[#E2D8C9] mt-6" data-testid="selected-scenario">
            <div className="flex items-center gap-2 text-[#4F6B3B] font-body text-sm font-bold mb-2">
              <CheckCircle2 className="w-4 h-4" /> السيناريو المختار
            </div>
            <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2">
              {order.selected_scenario_snapshot.title}
            </h3>
            <p className="font-body text-[#5A677D] leading-relaxed">
              {order.selected_scenario_snapshot.short_summary}
            </p>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}

function Info({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9]">
      <div className="text-xs text-[#8A9AB0] font-body">{label}</div>
      <div className="font-body font-bold text-[#2D3748] text-sm">{value}</div>
    </div>
  );
}
