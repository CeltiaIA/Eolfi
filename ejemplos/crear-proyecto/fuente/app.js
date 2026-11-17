// Muestra sintética propia de la guía «crear proyecto»: recetas guardadas en el navegador.
const lista = document.getElementById('lista');
const recetas = JSON.parse(localStorage.getItem('recetas') || '[]');
function pintar() {
  lista.replaceChildren(...recetas.map((r) => Object.assign(document.createElement('li'), { textContent: r.nombre })));
}
document.getElementById('nueva').addEventListener('submit', (e) => {
  e.preventDefault();
  const datos = new FormData(e.target);
  recetas.push({ nombre: datos.get('nombre'), ingredientes: datos.get('ingredientes') });
  localStorage.setItem('recetas', JSON.stringify(recetas));
  pintar();
});
pintar();
