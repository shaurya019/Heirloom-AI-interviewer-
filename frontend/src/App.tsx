import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ChaptersPage } from "./pages/ChaptersPage";
import { InterviewPage } from "./pages/InterviewPage";
import { MemoryExplorerPage } from "./pages/MemoryExplorerPage";
import { TimelinePage } from "./pages/TimelinePage";
import { TreePage } from "./pages/TreePage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/interview" replace />} />
        <Route path="/interview" element={<InterviewPage />} />
        <Route path="/tree" element={<TreePage />} />
        <Route path="/memories" element={<MemoryExplorerPage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/chapters" element={<ChaptersPage />} />
        <Route path="*" element={<Navigate to="/interview" replace />} />
      </Route>
    </Routes>
  );
}
