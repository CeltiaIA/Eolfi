// Muestra sintética propia (Eolfi): lista de notas en localStorage y alta por formulario.
const lista = document.getElementById('lista');
const notas = JSON.parse(localStorage.getItem('notas') || '[]');
function pintar() { lista.innerHTML = ''; for (const n of notas) { const li = document.createElement('li'); li.textContent = n; lista.append(li); } }
document.getElementById('nueva').addEventListener('submit', (e) => {
  e.preventDefault();
  notas.push(document.getElementById('texto').value);
  localStorage.setItem('notas', JSON.stringify(notas));
  fetch('/api/notas', { method: 'POST', body: JSON.stringify({ texto: notas.at(-1) }) }).catch(() => {});
  pintar();
});
pintar();
