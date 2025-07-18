async function uploadAudio() {
  const fileInput = document.getElementById("fileInput");
  const file = fileInput.files[0];

  if (!file) {
    alert("Please select a .wav file");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("http://localhost:8000/transcribe/", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      throw new Error("Upload failed");
    }

    const data = await res.json();
    document.getElementById("transcript").innerText = data.transcript;
    document.getElementById("intent").innerText = data.intent;
  } catch (err) {
    alert("Error uploading file");
    console.error(err);
  }
}
