import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Loader2, Sprout } from "lucide-react";
import { API, api } from "../lib/api";
import { usePageTitle } from "../lib/usePageTitle";

// What the family sees from a parent's private watch link: the story's video,
// cover and title — nothing else (no names of the parents, no photos).
export default function SharedStory() {
  usePageTitle("قصة من العائلة");
  const { token } = useParams();
  const [story, setStory] = useState(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);

  useEffect(() => {
    api.get(`/public/share/${token}`)
      .then(({ data }) => {
        setStory(data);
        document.title = data.title ? `${data.title} · غِراس` : "غِراس";
      })
      .catch(() => setGone(true));
  }, [token]);

  const base = `${API}/public/share/${encodeURIComponent(token)}`;
  return (
    <div className="min-h-screen bg-[#FDFBF7] font-body" dir="rtl" data-testid="shared-story">
      <div className="max-w-3xl mx-auto px-4 py-8 md:py-14">
        <div className="flex items-center gap-2 text-[#729352] font-heading font-bold text-xl mb-6">
          <Sprout className="w-6 h-6" /> غِراس
        </div>
        {gone ? (
          <div className="bg-white rounded-[2rem] p-8 border border-[#E2D8C9] text-center" data-testid="share-gone">
            <h1 className="font-heading text-2xl font-bold text-[#2D3748] mb-2">انتهت صلاحية هذا الرابط</h1>
            <p className="text-[#5A677D]">ألغاه صاحب القصة أو انتهت مدته. اطلب منه رابطاً جديداً.</p>
          </div>
        ) : !story ? (
          <div className="flex items-center justify-center gap-2 text-[#8A9AB0] py-20"><Loader2 className="w-5 h-5 animate-spin" /> جاري التحميل…</div>
        ) : (
          <>
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">{story.title}</h1>
            {story.child_name && <p className="text-[#5A677D] mb-5">قصة {story.child_name} 🌱</p>}
            <video
              src={`${base}/video`}
              poster={story.has_cover ? `${base}/cover` : undefined}
              controls playsInline preload="metadata"
              className="w-full aspect-video rounded-[1.5rem] bg-black shadow-lg"
              data-testid="shared-video"
            />
            <div className="bg-gradient-to-br from-[#E8F0E1] to-[#F8F1E7] rounded-[2rem] p-6 border border-[#E2D8C9] mt-6 text-center">
              <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-1">تريد قصة مثلها لطفلك؟</h2>
              <p className="text-sm text-[#5A677D] mb-4">احكِ لنا موقفاً عاشه طفلك، ليصبح بطل حكايته — فيلم كرتون وكتاب مصوّر.</p>
              <Link to="/" className="btn-primary inline-flex items-center gap-2" data-testid="shared-cta">
                <Sprout className="w-4 h-4" /> اصنع قصة لطفلك
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
