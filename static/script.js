document.getElementById('upload-form').addEventListener('submit', async function (e) {
  e.preventDefault();

  const formData = new FormData();
  const fileInput = this.querySelector('input[name="file"]');
  formData.append('file', fileInput.files[0]);

  const transcribeRes = await fetch('/transcribe/', {
    method: 'POST',
    body: formData
  });

  const { transcript, intent } = await transcribeRes.json();
  document.getElementById('transcript').textContent = transcript;
  document.getElementById('intent').textContent = intent;

  const assistRes = await fetch('/assist/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transcript, intent })
  });

  const { response, ai_takeover, audio_url } = await assistRes.json();
  document.getElementById('response').textContent = response;
  document.getElementById('takeover').textContent = ai_takeover ? 'Yes' : 'No';

  if (audio_url) {
    const audio = document.getElementById('audio-player');
    audio.src = audio_url;
    audio.style.display = 'block';
    audio.load();
  }
});
