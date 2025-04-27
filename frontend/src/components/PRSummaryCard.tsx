type PRSummaryCardProps = {
    pr_id: number;
    summary: string;
    onApprove: () => void;
    onReject: () => void;
  };
  
  export default function PRSummaryCard({
    pr_id,
    summary,
    onApprove,
    onReject,
  }: PRSummaryCardProps) {
    return (
      <div className="p-6 bg-gray-50 rounded-xl shadow-xl border border-purple-400 max-w-md mx-auto">
        <h3 className="text-2xl font-semibold text-gray-900 text-center mb-4">PR #{pr_id}</h3>
        <p className="text-gray-600 text-center mb-4">{summary}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onApprove}
            className="px-3 py-1.5 bg-green-500 hover:bg-green-600 text-white font-semibold rounded-md transition duration-150 cursor-pointer"
          >
            Approve
          </button>
          <button
            onClick={onReject}
            className="px-3 py-1.5 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-md transition duration-150 cursor-pointer"
          >
            Reject
          </button>
        </div>
      </div>
    );
  }
  