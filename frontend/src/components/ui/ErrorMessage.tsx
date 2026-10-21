type ErrorMessageProps = {
  title: string;
  message: string;
  onRetry?: () => void;
};

export function ErrorMessage({ title, message, onRetry }: ErrorMessageProps) {
  return (
    <div className="error-message" role="alert">
      <p className="error-message__title">{title}</p>
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
