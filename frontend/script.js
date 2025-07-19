async function uploadFile() {
    const fileInput = document.getElementById('audioFile');
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const transcribeRes = await fetch("/transcribe/", {
        method: "POST",
        body: formData
    });
    const { transcript, intent } = await transcribeRes.json();

    document.getElementById("transcript").textContent = transcript;
    document.getElementById("intent").textContent = intent;

    const assistRes = await fetch("/assist/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, intent })
    });
    const assistData = await assistRes.json();

    document.getElementById("response").textContent = assistData.response;
    document.getElementById("ai").textContent = assistData.ai_takeover ? "Yes" : "No";
}