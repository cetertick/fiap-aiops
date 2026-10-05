// inventory-api - FIAP AIOps teaching lab demo service.
//
// Go 1.22 + Gin. Business endpoints: GET /inventory, POST /inventory/reserve.
// Also exposes /health, /metrics (Prometheus), /chaos/* (chaos injection),
// structured JSON logs to stdout, and basic OpenTelemetry tracing (OTLP/gRPC).
//
// Kept intentionally small and readable for a live class.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
)

const appName = "inventory-api"
const port = "8002"

// ---------------------------------------------------------------------------
// Logging (structured JSON lines to stdout, scraped by Promtail/Loki)
// ---------------------------------------------------------------------------

func logJSON(level, msg string, fields map[string]interface{}) {
	record := map[string]interface{}{
		"level": level,
		"msg":   msg,
		"app":   appName,
		"ts":    time.Now().UTC().Format(time.RFC3339Nano),
	}
	for k, v := range fields {
		record[k] = v
	}
	b, err := json.Marshal(record)
	if err != nil {
		return
	}
	fmt.Println(string(b))
}

// ---------------------------------------------------------------------------
// OpenTelemetry tracing (minimal demo setup)
// ---------------------------------------------------------------------------

var tracer = otel.Tracer(appName)

func setupTracing() func() {
	endpoint := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
	if endpoint == "" {
		endpoint = "otel-collector.monitoring.svc.cluster.local:4317"
	}

	ctx := context.Background()
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		logJSON("error", "failed to create otlp exporter", map[string]interface{}{"error": err.Error()})
		return func() {}
	}

	res, _ := resource.New(ctx, resource.WithAttributes(
		semconv.ServiceName(appName),
	))

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)

	return func() {
		_ = tp.Shutdown(ctx)
	}
}

// ---------------------------------------------------------------------------
// Prometheus metrics
// ---------------------------------------------------------------------------

var (
	httpRequestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "http_requests_total",
		Help: "Total HTTP requests",
	}, []string{"method", "path", "status", "app"})

	httpRequestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name: "http_request_duration_seconds",
		Help: "HTTP request latency in seconds",
	}, []string{"method", "path", "app"})
)

// ---------------------------------------------------------------------------
// Chaos state
// ---------------------------------------------------------------------------
// mode: none | latency | crash | memory_leak | http_errors

var chaosDefaultIntensity = map[string]float64{
	"latency":     2000, // ms
	"http_errors": 50,   // percent
	"crash":       5,    // requests
	"memory_leak": 0,    // unused
	"none":        0,
}

type ChaosState struct {
	mu        sync.Mutex
	Enabled   bool    `json:"enabled"`
	Mode      string  `json:"mode"`
	Intensity float64 `json:"intensity"`
}

func (c *ChaosState) Snapshot() ChaosState {
	c.mu.Lock()
	defer c.mu.Unlock()
	return ChaosState{Enabled: c.Enabled, Mode: c.Mode, Intensity: c.Intensity}
}

var chaos = &ChaosState{}

var crashRequestCount int
var crashMu sync.Mutex

var memoryLeakBuffer [][]byte
var memoryLeakMu sync.Mutex

func envBool(key string, def bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return def
	}
	return b
}

func envFloat(key string, def float64) float64 {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return def
	}
	return f
}

func initChaosFromEnv() {
	chaos.mu.Lock()
	defer chaos.mu.Unlock()
	chaos.Enabled = envBool("CHAOS_ENABLED", false)
	mode := os.Getenv("CHAOS_MODE")
	if mode == "" {
		mode = "none"
	}
	chaos.Mode = mode
	chaos.Intensity = envFloat("CHAOS_INTENSITY", 0)
}

func memoryLeakLoop() {
	for {
		time.Sleep(1 * time.Second)
		snap := chaos.Snapshot()
		if snap.Enabled && snap.Mode == "memory_leak" {
			memoryLeakMu.Lock()
			memoryLeakBuffer = append(memoryLeakBuffer, make([]byte, 1024*1024)) // ~1MB
			total := len(memoryLeakBuffer)
			memoryLeakMu.Unlock()
			logJSON("error", "chaos: memory leak tick", map[string]interface{}{
				"method": "", "path": "", "status": 0, "duration_ms": 0,
				"total_leaked_mb": total,
			})
		}
	}
}

// applyChaos applies chaos effects for a business endpoint.
// Returns (shortCircuit, statusCode) - if shortCircuit is true the caller
// should respond with statusCode and stop; otherwise continue normally.
func applyChaos(method, path string) (bool, int) {
	snap := chaos.Snapshot()
	if !snap.Enabled || snap.Mode == "none" {
		return false, 0
	}

	switch snap.Mode {
	case "latency":
		delayMs := snap.Intensity
		if delayMs == 0 {
			delayMs = chaosDefaultIntensity["latency"]
		}
		logJSON("error", "chaos: injecting latency", map[string]interface{}{
			"method": method, "path": path, "status": 0, "duration_ms": delayMs,
		})
		time.Sleep(time.Duration(delayMs) * time.Millisecond)
		return false, 0

	case "http_errors":
		pct := snap.Intensity
		if pct == 0 {
			pct = chaosDefaultIntensity["http_errors"]
		}
		if rand.Float64()*100 < pct {
			logJSON("error", "chaos: injected 500", map[string]interface{}{
				"method": method, "path": path, "status": 500, "duration_ms": 0,
			})
			return true, http.StatusInternalServerError
		}
		return false, 0

	case "crash":
		limit := snap.Intensity
		if limit == 0 {
			limit = chaosDefaultIntensity["crash"]
		}
		crashMu.Lock()
		crashRequestCount++
		count := crashRequestCount
		crashMu.Unlock()
		logJSON("error", "chaos: crash mode request counted", map[string]interface{}{
			"method": method, "path": path, "status": 0, "duration_ms": 0,
			"request_count": count, "limit": limit,
		})
		if float64(count) >= limit {
			logJSON("error", "chaos: crashing on purpose", map[string]interface{}{
				"method": method, "path": path, "status": 0, "duration_ms": 0,
			})
			os.Exit(1)
		}
		return false, 0

	case "memory_leak":
		// handled by the background goroutine
		return false, 0
	}

	return false, 0
}

// ---------------------------------------------------------------------------
// Gin middleware
// ---------------------------------------------------------------------------

func metricsAndLoggingMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}
		method := c.Request.Method

		c.Next()

		status := c.Writer.Status()
		duration := time.Since(start)

		httpRequestsTotal.WithLabelValues(method, path, strconv.Itoa(status), appName).Inc()
		httpRequestDuration.WithLabelValues(method, path, appName).Observe(duration.Seconds())

		level := "info"
		if status >= 500 {
			level = "error"
		}
		logJSON(level, "request handled", map[string]interface{}{
			"method": method, "path": path, "status": status,
			"duration_ms": float64(duration.Microseconds()) / 1000.0,
		})
	}
}

// ---------------------------------------------------------------------------
// Business data
// ---------------------------------------------------------------------------

type stockItem struct {
	SKU      string `json:"sku"`
	Quantity int    `json:"quantity"`
}

var fakeInventory = map[string]int{
	"SKU-001": 120,
	"SKU-002": 45,
	"SKU-003": 0,
}

var inventoryMu sync.Mutex

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

func main() {
	initChaosFromEnv()
	go memoryLeakLoop()
	shutdownTracing := setupTracing()
	defer shutdownTracing()

	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(metricsAndLoggingMiddleware())

	router.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	router.GET("/metrics", gin.WrapH(promhttp.Handler()))

	router.GET("/chaos/status", func(c *gin.Context) {
		c.JSON(http.StatusOK, chaos.Snapshot())
	})

	router.POST("/chaos/enable", func(c *gin.Context) {
		var body struct {
			Mode      string   `json:"mode"`
			Intensity *float64 `json:"intensity"`
		}
		_ = c.ShouldBindJSON(&body)
		if body.Mode == "" {
			body.Mode = "none"
		}
		intensity := 0.0
		if body.Intensity != nil {
			intensity = *body.Intensity
		} else if def, ok := chaosDefaultIntensity[body.Mode]; ok {
			intensity = def
		}

		chaos.mu.Lock()
		chaos.Enabled = true
		chaos.Mode = body.Mode
		chaos.Intensity = intensity
		chaos.mu.Unlock()

		crashMu.Lock()
		crashRequestCount = 0
		crashMu.Unlock()

		logJSON("info", "chaos: enabled", map[string]interface{}{
			"method": "POST", "path": "/chaos/enable", "status": 200, "duration_ms": 0,
			"mode": body.Mode, "intensity": intensity,
		})
		c.JSON(http.StatusOK, chaos.Snapshot())
	})

	router.POST("/chaos/disable", func(c *gin.Context) {
		chaos.mu.Lock()
		chaos.Enabled = false
		chaos.Mode = "none"
		chaos.Intensity = 0
		chaos.mu.Unlock()

		crashMu.Lock()
		crashRequestCount = 0
		crashMu.Unlock()

		memoryLeakMu.Lock()
		memoryLeakBuffer = nil
		memoryLeakMu.Unlock()

		logJSON("info", "chaos: disabled", map[string]interface{}{
			"method": "POST", "path": "/chaos/disable", "status": 200, "duration_ms": 0,
		})
		c.JSON(http.StatusOK, chaos.Snapshot())
	})

	router.GET("/inventory", func(c *gin.Context) {
		ctx, span := tracer.Start(c.Request.Context(), "inventory-api.handle_inventory")
		defer span.End()
		c.Request = c.Request.WithContext(ctx)

		shortCircuit, status := applyChaos("GET", "/inventory")
		if shortCircuit {
			c.JSON(status, gin.H{"error": "chaos: injected failure"})
			return
		}

		inventoryMu.Lock()
		items := make([]stockItem, 0, len(fakeInventory))
		for sku, qty := range fakeInventory {
			items = append(items, stockItem{SKU: sku, Quantity: qty})
		}
		inventoryMu.Unlock()

		c.JSON(http.StatusOK, gin.H{"inventory": items})
	})

	router.POST("/inventory/reserve", func(c *gin.Context) {
		ctx, span := tracer.Start(c.Request.Context(), "inventory-api.handle_inventory")
		defer span.End()
		c.Request = c.Request.WithContext(ctx)

		shortCircuit, status := applyChaos("POST", "/inventory/reserve")
		if shortCircuit {
			c.JSON(status, gin.H{"error": "chaos: injected failure"})
			return
		}

		var body struct {
			SKU      string `json:"sku"`
			Quantity int    `json:"quantity"`
		}
		if err := c.ShouldBindJSON(&body); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid body"})
			return
		}

		inventoryMu.Lock()
		available, ok := fakeInventory[body.SKU]
		reserved := false
		if ok && available >= body.Quantity {
			fakeInventory[body.SKU] = available - body.Quantity
			reserved = true
		}
		remaining := fakeInventory[body.SKU]
		inventoryMu.Unlock()

		c.JSON(http.StatusOK, gin.H{
			"sku":       body.SKU,
			"reserved":  reserved,
			"remaining": remaining,
		})
	})

	addr := ":" + port
	logJSON("info", fmt.Sprintf("%s listening on port %s", appName, port), map[string]interface{}{
		"method": "", "path": "", "status": 0, "duration_ms": 0,
	})
	if err := router.Run(addr); err != nil {
		logJSON("error", "server exited", map[string]interface{}{"error": err.Error()})
		os.Exit(1)
	}
}
