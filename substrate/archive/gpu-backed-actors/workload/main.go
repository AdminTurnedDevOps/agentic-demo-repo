// gpu-agent is a tiny HTTP actor that uses a GPU as a tool, not as
// long-lived process state.
//
// On boot it runs nvidia-smi in a child process, then serves HTTP. The
// long-running process never opens a CUDA context, so gVisor can take the
// golden snapshot and later suspend/resume the actor. GET /gpu runs
// nvidia-smi again the same way — the pattern an agent uses for a GPU tool
// call.
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const listenAddr = ":80"

// runSMI invokes nvidia-smi. Tests replace it.
var runSMI = nvidiaSMI

func main() {
	boot, err := probeGPU()
	if err != nil {
		log.Fatalf("gpu probe failed: %v\n%s", err, boot)
	}
	log.Print(boot)

	mux := http.NewServeMux()
	mux.HandleFunc("/readyz", handleReadyz)
	mux.HandleFunc("/gpu", handleGPU)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		fmt.Fprintf(w, "actor=gpu-agent\nboot_probe:\n%s", boot)
	})

	log.Printf("STATUS_SERVER_READY %s", listenAddr)
	if err := http.ListenAndServe(listenAddr, mux); err != nil {
		log.Fatal(err)
	}
}

func handleReadyz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok\n"))
}

func handleGPU(w http.ResponseWriter, _ *http.Request) {
	out, err := probeGPU()
	if err != nil {
		http.Error(w, strings.TrimSpace(out+"\n"+err.Error())+"\n", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write([]byte(out))
}

func probeGPU() (string, error) {
	var b strings.Builder
	devices, _ := filepath.Glob("/dev/nvidia[0-9]*")
	fmt.Fprintf(&b, "devices=%s\n", strings.Join(devices, ","))

	smi, err := runSMI()
	b.WriteString(smi)
	if err != nil {
		return b.String(), err
	}
	if !strings.Contains(smi, "NVIDIA") && len(devices) == 0 {
		return b.String(), fmt.Errorf("nvidia-smi produced no NVIDIA output")
	}
	return b.String(), nil
}

func nvidiaSMI() (string, error) {
	bins := []string{"nvidia-smi", "/usr/local/nvidia/bin/nvidia-smi"}
	if override := os.Getenv("NVIDIA_SMI"); override != "" {
		bins = []string{override}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	var lastOut []byte
	var lastErr error
	for _, bin := range bins {
		out, err := exec.CommandContext(ctx, bin).CombinedOutput()
		if err == nil {
			return string(out), nil
		}
		lastOut, lastErr = out, err
	}
	return string(lastOut), fmt.Errorf("nvidia-smi: %w", lastErr)
}
