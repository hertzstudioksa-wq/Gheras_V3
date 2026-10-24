import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, ScrollText } from "lucide-react";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";

// Privacy policy and terms (audit CS-7). Every statement here matches what the
// code does: photo deletion (services/privacy_service.py), account deletion
// (/account), media links that expire, card data only on Moyasar's page.
// Update both when the providers or the retention period change.

const UPDATED = "24 أكتوبر 2026";

const PRIVACY = [
  ["مين إحنا", [
    "غِراس منصة بتعمل لطفلك قصة مخصّصة (فيديو وكتاب) بطلها هو، بمساعدة الذكاء الاصطناعي. السياسة دي بتشرح بنجمع إيه، وبنستخدمه في إيه، وإزاي تمسحه.",
  ]],
  ["البيانات اللي بنجمعها", [
    "حسابك: الاسم والإيميل وكلمة السر (متخزّنة مشفّرة، ومحدش يقدر يقراها).",
    "بيانات القصة: اسم طفلك وعمره، والصور اللي بترفعها له وللأقارب أو للعبته، والقيمة والموقف والملاحظات اللي بتكتبها.",
    "الدفع: المبلغ وحالة الدفع بس. بيانات البطاقة بتتكتب على صفحة ميسر مباشرة ومش بتوصلنا خالص.",
    "بيانات تقنية بسيطة: عنوان الـ IP وقت الدخول، عشان نحمي الحسابات من محاولات التخمين.",
  ]],
  ["بنستخدمها في إيه", [
    "نكتب قصة طفلك، ونرسم شخصيته وشخصيات عيلته والمشاهد، ونعمل السرد والموسيقى والفيديو والكتاب.",
    "نحصّل سعر القصة، ونحمي حسابك.",
    "مش بنبيع بياناتك، ومش بنستخدم صور طفلك في أي إعلان أو عرض، ومش بندرّب بيها أي موديل.",
  ]],
  ["مين بيشوف البيانات", [
    "عشان نعمل القصة بنبعت الجزء اللازم من البيانات لمزوّدي ذكاء اصطناعي برّه المملكة: fal.ai (رسم الصور والفيديو والموسيقى وكتابة النص بموديلات زي Claude وGPT)، وGoogle Gemini (صوت السرد)، وممكن OpenAI أو Anthropic مباشرة. كل مزوّد بياخد اللي يلزم الخطوة بتاعته بس.",
    "الدفع بيتم عن طريق ميسر (Moyasar).",
    "فريق غِراس بيشوف الطلب لما يحتاج يتابعه أو يصلّح مشكلة فيه.",
  ]],
  ["بنحتفظ بالبيانات قد إيه", [
    "الصور الأصلية اللي رفعتها بتتمسح تلقائياً بعد تسليم القصة بـ 30 يوم، وتقدر تمسحها بنفسك قبلها من صفحة القصة.",
    "القصة النهائية والرسومات بتفضل في حسابك لحد ما تمسح حسابك.",
    "لو مسحت حسابك، بنمسح اسمك وإيميلك وكل الملفات وبيانات طفلك من الطلبات. سجل المبالغ المدفوعة بيفضل للمحاسبة من غير أي بيانات شخصية.",
  ]],
  ["حقوقك", [
    "تشوف قصصك وبياناتك في حسابك في أي وقت.",
    "تمسح الصور الأصلية لأي قصة اتسلّمت.",
    "تمسح حسابك وكل بياناته من صفحة «حسابي».",
  ]],
  ["الأطفال", [
    "الخدمة لأولياء الأمور (18 سنة فأكبر). الطفل نفسه مش بيعمل حساب، وأي صورة بتترفع لازم تكون من ولي أمره أو بإذنه.",
  ]],
  ["الحماية", [
    "الصور والقصص مش بتفتح إلا لصاحب الحساب. روابط الملفات مؤقتة، وكلمات السر مشفّرة، والدخول عليه حد للمحاولات.",
  ]],
];

const TERMS = [
  ["الخدمة", [
    "غِراس بتعمل قصص أطفال مخصّصة بالذكاء الاصطناعي. الرسم بيكون مستوحى من الصورة، ومش لازم يطابقها مطابقة كاملة، والنتيجة ممكن تختلف من قصة للتانية.",
  ]],
  ["حسابك", [
    "لازم تكون 18 سنة فأكبر، وولي أمر الطفل أو عندك إذن منه. إنت مسؤول عن سرية كلمة السر.",
  ]],
  ["الصور والمحتوى اللي بترفعه", [
    "لازم يكون من حقك أو عندك إذن تستخدمه. ممنوع ترفع صور لأطفال مش تحت ولايتك من غير إذن ولي أمرهم، وممنوع أي محتوى مسيء أو غير لائق. من حقنا نرفض أي طلب مخالف.",
  ]],
  ["الأسعار والدفع", [
    "سعر القصة بيظهر قبل ما تطلب، حسب المدة ونوع المخرج والجودة. الدفع بيتم بعد ما تختار فكرة القصة وقبل ما نبدأ نجهّزها.",
    "الرصيد بيدفع أي قصة، والهدية اللي مع الشحن جزء من الرصيد. الضريبة (لو مطبّقة) بتتحسب وقت شراء القصة.",
  ]],
  ["لو حصلت مشكلة", [
    "لو التجهيز وقف تقدر تعيد المحاولة من صفحة القصة. ولو ما قدرناش نسلّم القصة، بنرجّع المبلغ لرصيدك في غِراس.",
  ]],
  ["ملكية القصة", [
    "القصة النهائية ليك ولعيلتك للاستخدام الشخصي، وتقدر تشاركها مع حبايبك. ممنوع بيعها أو استخدامها تجارياً. المنصة والقوالب والتصميم ملك غِراس.",
  ]],
  ["تعديل الشروط", [
    "ممكن نحدّث الشروط أو سياسة الخصوصية، وبنكتب تاريخ آخر تحديث هنا. التعديل المهم بنبلّغك بيه قبل ما يتطبّق على طلب جديد.",
  ]],
];

export default function LegalPage({ kind }) {
  const [email, setEmail] = useState("");
  useEffect(() => {
    api.get("/public/content").then((r) => setEmail((r.data || {})["footer.contact_email"] || "")).catch(() => {});
  }, []);
  const privacy = kind === "privacy";
  const sections = privacy ? PRIVACY : TERMS;
  const Icon = privacy ? ShieldCheck : ScrollText;
  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid={`legal-${kind}`}>
      <Navbar />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-10 md:py-14">
        <div className="inline-flex items-center gap-2 bg-[#E8F0E1] rounded-full px-3 py-1 text-xs font-bold text-[#4F6B3B] mb-3">
          <Icon className="w-3.5 h-3.5" /> آخر تحديث: {UPDATED}
        </div>
        <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-8">
          {privacy ? "سياسة الخصوصية" : "الشروط والأحكام"}
        </h1>
        <div className="space-y-6">
          {sections.map(([title, paras]) => (
            <section key={title} className="bg-white rounded-3xl border border-[#E2D8C9] p-5 md:p-6">
              <h2 className="font-heading text-xl font-bold text-[#729352] mb-3">{title}</h2>
              <ul className="space-y-2 font-body text-[#2D3748] leading-relaxed list-disc pr-5">
                {paras.map((p) => <li key={p}>{p}</li>)}
              </ul>
            </section>
          ))}
          <section className="bg-[#F8F1E7] rounded-3xl border border-[#E2D8C9] p-5 md:p-6 font-body text-[#2D3748]">
            <h2 className="font-heading text-xl font-bold text-[#8B5A2B] mb-2">تواصل معانا</h2>
            {email
              ? <p>أي سؤال أو طلب بخصوص بياناتك: <a href={`mailto:${email}`} className="font-bold underline" dir="ltr">{email}</a></p>
              : <p>تقدر تمسح صورك أو حسابك بنفسك من <Link to="/account" className="font-bold underline">صفحة حسابي</Link>.</p>}
            <p className="mt-2 text-sm">
              {privacy ? <Link to="/terms" className="underline">اقرأ الشروط والأحكام</Link> : <Link to="/privacy" className="underline">اقرأ سياسة الخصوصية</Link>}
            </p>
          </section>
        </div>
      </main>
      <Footer />
    </div>
  );
}
