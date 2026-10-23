import React from "react";

/**
 * Catches render errors so one broken page doesn't unmount the whole app
 * (React leaves a blank screen otherwise). Pass `resetKey` (e.g. the current
 * pathname) to clear the error when the user navigates away.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info?.componentStack);
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="bg-white rounded-3xl p-6 border border-[#E2D8C9] max-w-xl mx-auto my-10 text-center" data-testid="error-boundary">
        <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-2">حدث خطأ غير متوقع في هذه الصفحة</h2>
        <p className="font-body text-[#5A677D] mb-4">جرّب إعادة تحميل الصفحة. لو تكرر الخطأ، أبلغ فريق الدعم.</p>
        <button onClick={() => window.location.reload()} className="btn-primary">إعادة تحميل</button>
      </div>
    );
  }
}
