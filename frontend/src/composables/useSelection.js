import { reactive } from "vue";

export function useSelection(setMessage) {
  const currentResume = reactive({
    id: null,
    localId: null,
    fileName: "",
    contentPreview: "",
    content: "",
  });
  const currentJob = reactive({
    id: null,
    localId: null,
    company: "",
    title: "",
    jdText: "",
  });

  function applyResumeSelection(resume) {
    if (!resume) return;
    currentResume.id = resume.id ?? resume.resume_id ?? null;
    currentResume.localId = resume.local_resume_id ?? null;
    currentResume.fileName = resume.file_name || "";
    currentResume.contentPreview =
      resume.content_preview || String(resume.content || "").slice(0, 200);
    currentResume.content = resume.content || "";
    setMessage(`已选中第 ${currentResume.localId} 份简历。`);
  }

  function applyJobSelection(job) {
    if (!job) return;
    currentJob.id = job.id ?? job.job_id ?? null;
    currentJob.localId = job.local_job_id ?? null;
    currentJob.company = job.company || "";
    currentJob.title = job.title || "";
    currentJob.jdText = job.jd_text || job.jd_preview || "";
    setMessage(`已选中第 ${currentJob.localId} 个岗位。`);
  }

  function resetSelections() {
    currentResume.id = null;
    currentResume.localId = null;
    currentResume.fileName = "";
    currentResume.contentPreview = "";
    currentResume.content = "";

    currentJob.id = null;
    currentJob.localId = null;
    currentJob.company = "";
    currentJob.title = "";
    currentJob.jdText = "";
  }

  return {
    applyJobSelection,
    applyResumeSelection,
    currentJob,
    currentResume,
    resetSelections,
  };
}
