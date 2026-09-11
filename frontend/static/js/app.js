async function loadDocuments() {
  const tbody = document.getElementById("doc-rows");
  const empty = document.getElementById("empty-state");
  try {
    const res = await fetch("/api/v1/documents");
    const body = await res.json();
    tbody.innerHTML = "";
    if (!body.documents || body.documents.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    for (const doc of body.documents) {
      const tr = document.createElement("tr");
      tr.className = "row-link";
      tr.onclick = () => (window.location.href = `/documents/${encodeURIComponent(doc.document_name)}`);
      const confidence = doc.overall_confidence != null ? (doc.overall_confidence * 100).toFixed(1) + "%" : "—";
      tr.innerHTML = `
        <td>${doc.document_name}</td>
        <td>${doc.document_type}</td>
        <td><span class="badge ${doc.processing_status}">${doc.processing_status}</span></td>
        <td>${confidence}</td>
        <td class="muted">${new Date(doc.processed_at).toLocaleString()}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (err) {
    empty.textContent = "Could not load processed documents.";
    empty.style.display = "block";
  }
}

function setupUploadForm() {
  const form = document.getElementById("upload-form");
  if (!form) return;
  const button = form.querySelector("button");
  const status = document.getElementById("upload-status");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById("file-input");
    const typeSelect = document.getElementById("document-type");
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("document_type", typeSelect.value);

    button.disabled = true;
    status.textContent = "Processing… this can take a few seconds for scanned documents.";
    status.className = "muted";

    try {
      const res = await fetch("/api/v1/documents/process", { method: "POST", body: formData });
      const body = await res.json();
      if (body.error) {
        status.textContent = `Error: ${body.error.message}`;
        status.className = "field-value missing";
      } else {
        status.textContent = `Processed "${body.document_name}" — status: ${body.processing_status}`;
        status.className = "muted";
        form.reset();
        loadDocuments();
      }
    } catch (err) {
      status.textContent = "Upload failed: could not reach the server.";
      status.className = "field-value missing";
    } finally {
      button.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupUploadForm();
  loadDocuments();
});
