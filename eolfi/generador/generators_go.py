"""Destino Go (PLAN_DEFINITIVO.md, D2; 18/11/2026): servidor web y API REST en Go con SOLO la biblioteca estándar.

- `net/http` con las rutas por método de Go 1.22 (`GET /api/{recurso}/{id}`), un almacén en memoria por recurso y
  las mismas respuestas que Express (`{"error": …}` con 404/422).
- La web propia (las mismas páginas que el destino estático) va dentro del ejecutable con `embed`.
- Cabeceras de seguridad en todas las respuestas, cuerpo limitado a 64 KiB y tiempos de espera del servidor.
- Sin dependencias: `go vet`, `go test` y `go build` funcionan sin red (la verificación pone `GOPROXY=off`).
- Un solo ejecutable; `APP_SMOKE=1` lo arranca en un puerto libre, se pide a sí mismo `/api/health` y la portada y
  termina (prueba de humo de la verificación).
- `--db sqlite` y `--auth` no aplican a este destino (lo anota la especificación).
"""
from __future__ import annotations

import json
import re
from typing import Any

from eolfi.generador.generators import SECURITY_HEADERS, Writer, _write_static_site


def module_name(spec: dict[str, Any]) -> str:
    m = re.sub(r"[^a-z0-9-]", "-", str(spec.get("name") or "app").lower()).strip("-") or "app"
    return m if m[0].isalpha() else "app-" + m


def binary_name(spec: dict[str, Any]) -> str:
    return module_name(spec)


GO_MAIN = '''// Servidor de __TITLE__ (generado por Eolfi): API REST y web propia, solo con la biblioteca estándar de Go.
//
//	go run .                 # http://127.0.0.1:8000
//	HOST=0.0.0.0 PORT=9000 go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

func main() {
	if os.Getenv("APP_SMOKE") == "1" {
		if err := smoke(); err != nil {
			fmt.Fprintln(os.Stderr, "smoke:", err)
			os.Exit(1)
		}
		fmt.Println("smoke ok")
		return
	}
	host := envOr("HOST", "127.0.0.1")
	port := envOr("PORT", "8000")
	srv := newHTTPServer(net.JoinHostPort(host, port))
	log.Printf("%s en http://%s", appTitle, srv.Addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

// appTitle es el nombre de la aplicación.
const appTitle = __TITLE_GO__

func envOr(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func newHTTPServer(addr string) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           newServer(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}

// smoke arranca el servidor en un puerto libre de 127.0.0.1, se pide /api/health y la portada y se apaga.
func smoke() error {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	srv := newHTTPServer(ln.Addr().String())
	go srv.Serve(ln)
	defer srv.Shutdown(context.Background())
	client := &http.Client{Timeout: 5 * time.Second}
	for _, path := range []string{"/api/health", "/"} {
		resp, err := client.Get("http://" + ln.Addr().String() + path)
		if err != nil {
			return err
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusOK || len(body) == 0 {
			return fmt.Errorf("%s: %d", path, resp.StatusCode)
		}
		if resp.Header.Get("Content-Security-Policy") == "" {
			return fmt.Errorf("%s: falta Content-Security-Policy", path)
		}
	}
	return nil
}
'''

GO_STORE = '''package main

import (
	"sort"
	"sync"
)

// Item es un elemento de un recurso de la API.
type Item struct {
	ID          int     `json:"id"`
	Name        string  `json:"name"`
	Description *string `json:"description"`
}

// Store guarda los elementos de un recurso en memoria (se pierden al reiniciar), seguro entre goroutines.
type Store struct {
	mu     sync.RWMutex
	items  map[int]Item
	nextID int
}

func NewStore() *Store {
	return &Store{items: map[int]Item{}, nextID: 1}
}

func (s *Store) List() []Item {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Item, 0, len(s.items))
	for _, it := range s.items {
		out = append(out, it)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func (s *Store) Get(id int) (Item, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	it, ok := s.items[id]
	return it, ok
}

func (s *Store) Create(name string, description *string) Item {
	s.mu.Lock()
	defer s.mu.Unlock()
	it := Item{ID: s.nextID, Name: name, Description: description}
	s.items[it.ID] = it
	s.nextID++
	return it
}

func (s *Store) Update(id int, name string, description *string) (Item, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.items[id]; !ok {
		return Item{}, false
	}
	it := Item{ID: id, Name: name, Description: description}
	s.items[id] = it
	return it, true
}

func (s *Store) Delete(id int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.items[id]; !ok {
		return false
	}
	delete(s.items, id)
	return true
}
'''

GO_SERVER = '''package main

import (
	"embed"
	"encoding/json"
	"io/fs"
	"net/http"
	"strconv"
	"strings"
	"unicode/utf8"
)

//go:embed web
var webFiles embed.FS

// Recursos de la API detectados en las fuentes analizadas.
var resources = []string{__RESOURCES__}

var securityHeaders = map[string]string{
__HEADERS__}

const maxBody = 64 << 10 // 64 KiB por petición

type itemIn struct {
	Name        *string         `json:"name"`
	Description json.RawMessage `json:"description"`
}

func newServer() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "db": "memory", "auth": false})
	})
	for _, name := range resources {
		store := NewStore()
		example := "Dato de ejemplo"
		store.Create("Primer elemento de "+name, &example)
		base := "/api/" + name
		mux.HandleFunc("GET "+base, func(w http.ResponseWriter, r *http.Request) {
			writeJSON(w, http.StatusOK, store.List())
		})
		mux.HandleFunc("POST "+base, func(w http.ResponseWriter, r *http.Request) {
			name, desc, msg := readItem(w, r)
			if msg != "" {
				writeError(w, http.StatusUnprocessableEntity, msg)
				return
			}
			writeJSON(w, http.StatusCreated, store.Create(name, desc))
		})
		mux.HandleFunc("GET "+base+"/{id}", func(w http.ResponseWriter, r *http.Request) {
			id, ok := itemID(r)
			it, found := store.Get(id)
			if !ok || !found {
				writeError(w, http.StatusNotFound, "No encontrado")
				return
			}
			writeJSON(w, http.StatusOK, it)
		})
		mux.HandleFunc("PUT "+base+"/{id}", func(w http.ResponseWriter, r *http.Request) {
			id, ok := itemID(r)
			if !ok {
				writeError(w, http.StatusNotFound, "No encontrado")
				return
			}
			name, desc, msg := readItem(w, r)
			if msg != "" {
				writeError(w, http.StatusUnprocessableEntity, msg)
				return
			}
			it, found := store.Update(id, name, desc)
			if !found {
				writeError(w, http.StatusNotFound, "No encontrado")
				return
			}
			writeJSON(w, http.StatusOK, it)
		})
		mux.HandleFunc("DELETE "+base+"/{id}", func(w http.ResponseWriter, r *http.Request) {
			id, ok := itemID(r)
			if !ok || !store.Delete(id) {
				writeError(w, http.StatusNotFound, "No encontrado")
				return
			}
			w.WriteHeader(http.StatusNoContent)
		})
	}
	// Una ruta de la API que no existe responde JSON, no la web.
	mux.HandleFunc("/api/", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "No encontrado")
	})
	site, err := fs.Sub(webFiles, "web")
	if err != nil {
		panic(err)
	}
	mux.Handle("/", http.FileServerFS(site))
	return withSecurityHeaders(mux)
}

func withSecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		for k, v := range securityHeaders {
			w.Header().Set(k, v)
		}
		next.ServeHTTP(w, r)
	})
}

func itemID(r *http.Request) (int, bool) {
	id, err := strconv.Atoi(r.PathValue("id"))
	return id, err == nil && id > 0
}

// readItem valida el cuerpo: name obligatorio (1-200 caracteres) y description texto opcional (máx. 2000).
func readItem(w http.ResponseWriter, r *http.Request) (string, *string, string) {
	var in itemIn
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBody))
	if err := dec.Decode(&in); err != nil {
		return "", nil, "JSON inválido"
	}
	if in.Name == nil {
		return "", nil, "name es obligatorio (1-200 caracteres)"
	}
	name := strings.TrimSpace(*in.Name)
	if n := utf8.RuneCountInString(name); n < 1 || n > 200 {
		return "", nil, "name es obligatorio (1-200 caracteres)"
	}
	var desc *string
	if len(in.Description) > 0 && string(in.Description) != "null" {
		var d string
		if err := json.Unmarshal(in.Description, &d); err != nil || utf8.RuneCountInString(d) > 2000 {
			return "", nil, "description debe ser texto (máx. 2000)"
		}
		desc = &d
	}
	return name, desc, ""
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
'''

GO_TEST = '''package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func call(t *testing.T, h http.Handler, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestHealth(t *testing.T) {
	rec := call(t, newServer(), "GET", "/api/health", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"ok":true`) {
		t.Fatalf("health: %d %s", rec.Code, rec.Body)
	}
}

func TestCRUD(t *testing.T) {
	h := newServer()
	rec := call(t, h, "GET", "/api/__FIRST__", "")
	var items []Item
	if err := json.Unmarshal(rec.Body.Bytes(), &items); err != nil || rec.Code != 200 || len(items) != 1 {
		t.Fatalf("lista inicial: %d %s", rec.Code, rec.Body)
	}
	rec = call(t, h, "POST", "/api/__FIRST__", `{"name": "  Nuevo  ", "description": "Detalle"}`)
	var created Item
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil || rec.Code != 201 || created.Name != "Nuevo" {
		t.Fatalf("crear: %d %s", rec.Code, rec.Body)
	}
	path := "/api/__FIRST__/" + itoa(created.ID)
	if rec = call(t, h, "PUT", path, `{"name": "Cambiado"}`); rec.Code != 200 || !strings.Contains(rec.Body.String(), "Cambiado") {
		t.Fatalf("actualizar: %d %s", rec.Code, rec.Body)
	}
	if rec = call(t, h, "GET", path, ""); rec.Code != 200 {
		t.Fatalf("ver: %d", rec.Code)
	}
	if rec = call(t, h, "DELETE", path, ""); rec.Code != 204 {
		t.Fatalf("borrar: %d", rec.Code)
	}
	if rec = call(t, h, "GET", path, ""); rec.Code != 404 {
		t.Fatalf("tras borrar: %d", rec.Code)
	}
}

func TestValidation(t *testing.T) {
	h := newServer()
	for _, body := range []string{`{}`, `{"name": ""}`, `{"name": "` + strings.Repeat("x", 201) + `"}`,
		`{"name": "a", "description": 5}`, `no es json`} {
		if rec := call(t, h, "POST", "/api/__FIRST__", body); rec.Code != 422 {
			t.Fatalf("%s: %d", body, rec.Code)
		}
	}
	if rec := call(t, h, "POST", "/api/__FIRST__", `{"name": "`+strings.Repeat("x", 70<<10)+`"}`); rec.Code != 422 {
		t.Fatalf("cuerpo enorme: %d", rec.Code)
	}
	for _, path := range []string{"/api/__FIRST__/0", "/api/__FIRST__/abc", "/api/__FIRST__/999", "/api/no-existe"} {
		if rec := call(t, h, "GET", path, ""); rec.Code != 404 {
			t.Fatalf("%s: %d", path, rec.Code)
		}
	}
}

func TestWebAndSecurityHeaders(t *testing.T) {
	h := newServer()
	rec := call(t, h, "GET", "/", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "<main") {
		t.Fatalf("portada: %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), `lang="__LANG__"`) {
		t.Fatal("la portada no declara el idioma")
	}
	for _, path := range []string{"/", "/api/health", "/api/__FIRST__/999"} {
		rec := call(t, h, "GET", path, "")
		for k := range securityHeaders {
			if rec.Header().Get(k) == "" {
				t.Fatalf("%s: falta la cabecera %s", path, k)
			}
		}
	}
}

func itoa(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}
'''

GO_GITIGNORE_EXTRA = "/bin/\n*.exe\n"


def gen_go(spec: dict[str, Any], w: Writer) -> None:
    resources = spec["api"]["resources"] or ["items"]
    title = spec["title"].replace("\\", "").replace("\n", " ").replace("*/", "")
    w("go.mod", f"module {module_name(spec)}\n\ngo 1.22\n")
    w("main.go", GO_MAIN.replace("__TITLE_GO__", json.dumps(spec["title"], ensure_ascii=False))
      .replace("__TITLE__", title))
    w("store.go", GO_STORE)
    headers = "".join(f"\t{json.dumps(k)}: {json.dumps(v)},\n" for k, v in SECURITY_HEADERS.items())
    w("server.go", GO_SERVER.replace("__RESOURCES__", ", ".join(json.dumps(r) for r in resources))
      .replace("__HEADERS__", headers))
    lang = "en" if spec.get("idioma") == "en" else "es"
    w("server_test.go", GO_TEST.replace("__FIRST__", resources[0]).replace("__LANG__", lang))
    # La web no tiene inicio de sesión en este destino: se escribe como si no se hubiera pedido --auth.
    web_spec = {**spec, "options": {**(spec.get("options") or {}), "auth": False}}
    _write_static_site(web_spec, w, "web/", resources)
    w(".gitignore.extra", GO_GITIGNORE_EXTRA)
