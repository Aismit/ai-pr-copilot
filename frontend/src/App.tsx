import reactLogo from './assets/react.svg'
import viteLogo from '/vite.svg'
import './App.css'
import { useEffect, useState } from 'react';

import PRSummaryCard from "./components/PRSummaryCard";

function App() {
  const [prSummaries, setPrSummaries] = useState([]);

  useEffect(() => {
    fetch('http://localhost:8000/pr-summaries')
      .then(res => res.json())
      .then(data => setPrSummaries(data))
      .catch(err => console.error(err));
  }, []);

  const handleApprove = (pr_id: number) => {
    fetch(`http://localhost:8000/pr/${pr_id}/approve`, { method: "POST" })
      .then(() => console.log(`Approved PR #${pr_id}`))
      .catch(console.error);
  };

  const handleReject = (pr_id: number) => {
    fetch(`http://localhost:8000/pr/${pr_id}/reject`, { method: "POST" })
      .then(() => console.log(`Rejected PR #${pr_id}`))
      .catch(console.error);
  };

  return (
    <div className="min-h-screen flex flex-col items-center p-8">
      <h1 className="text-3xl font-bold mb-8">PR Copilot Dashboard</h1>
      {prSummaries.map((pr: any) => (
        <PRSummaryCard
          key={pr.pr_id}
          pr_id={pr.pr_id}
          summary={pr.summary}
          onApprove={() => handleApprove(pr.pr_id)}
          onReject={() => handleReject(pr.pr_id)}
        />
      ))}
    </div>
  );
}

export default App;

