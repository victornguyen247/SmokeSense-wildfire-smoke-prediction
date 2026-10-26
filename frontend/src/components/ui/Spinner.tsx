type SpinnerProps = {
  /** Read by screen readers and shown next to the spinner. */
  label: string;
};

export function Spinner({ label }: SpinnerProps) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <span className="spinner__circle" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
