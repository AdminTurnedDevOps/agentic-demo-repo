package main

import (
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestProbeGPUSuccess(t *testing.T) {
	orig := runSMI
	t.Cleanup(func() { runSMI = orig })
	runSMI = func() (string, error) {
		return "NVIDIA Tesla T4\n", nil
	}

	out, err := probeGPU()
	if err != nil {
		t.Fatalf("probeGPU: %v", err)
	}
	if !strings.Contains(out, "NVIDIA Tesla T4") {
		t.Fatalf("probe output missing nvidia-smi text:\n%s", out)
	}
}

func TestProbeGPUFailure(t *testing.T) {
	orig := runSMI
	t.Cleanup(func() { runSMI = orig })
	runSMI = func() (string, error) {
		return "no devices\n", errors.New("nvidia-smi failed")
	}

	if _, err := probeGPU(); err == nil {
		t.Fatal("expected probeGPU to fail")
	}

	runSMI = func() (string, error) {
		return "no gpu here\n", nil
	}
	if _, err := probeGPU(); err == nil {
		t.Fatal("expected probeGPU to fail when nvidia-smi omits NVIDIA")
	}
}

func TestReadyzAndGPUHandlers(t *testing.T) {
	orig := runSMI
	t.Cleanup(func() { runSMI = orig })
	runSMI = func() (string, error) {
		return "NVIDIA Tesla T4\n", nil
	}

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	handleReadyz(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("readyz status %d", rec.Code)
	}
	body, _ := io.ReadAll(rec.Body)
	if string(body) != "ok\n" {
		t.Fatalf("readyz body %q", body)
	}

	req = httptest.NewRequest(http.MethodGet, "/gpu", nil)
	rec = httptest.NewRecorder()
	handleGPU(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("/gpu status %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "NVIDIA Tesla T4") {
		t.Fatalf("/gpu body:\n%s", rec.Body.String())
	}
}
