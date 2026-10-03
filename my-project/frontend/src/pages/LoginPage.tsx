export function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-lg shadow-md p-8">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">Sign In</h2>
        <p className="text-gray-500 mb-6">
          Authentication will be implemented in Phase 2.
        </p>
        <button
          type="button"
          disabled
          className="w-full py-2 px-4 bg-indigo-600 text-white rounded-md opacity-50 cursor-not-allowed"
        >
          Login
        </button>
      </div>
    </div>
  );
}
