package logx

import (
	"fmt"
	"io"
	"os"
	"path"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/sirupsen/logrus"
)

type logger struct {
	entry *logrus.Entry
}

func (l *logger) Write(p []byte) (n int, err error) {
	return l.entry.WriterLevel(logrus.InfoLevel).Write(p)
}

// Trace logs a message at trace level.
func (l *logger) Trace(msg string) {
	l.entry.Trace(msg)
}

func (l *logger) Debug(msg string) {
	l.entry.Debug(msg)
}

func (l *logger) Info(msg string) {
	l.entry.Info(msg)
}

func (l *logger) Warn(msg string) {
	l.entry.Warn(msg)
}

func (l *logger) Error(msg string) {
	l.entry.Error(msg)
}

func (l *logger) Fatal(msg string) {
	l.entry.Fatal(msg)
}

func (l *logger) Panic(msg string) {
	l.entry.Panic(msg)
}

func (l *logger) WithField(key string, value any) Logger {
	return &logger{entry: l.entry.WithField(key, value)}
}

func (l *logger) WithFields(fields Fields) Logger {
	logrusFields := make(logrus.Fields)
	for k, v := range fields {
		logrusFields[k] = v
	}
	return &logger{entry: l.entry.WithFields(logrusFields)}
}

func (l *logger) WithError(err error) Logger {
	return &logger{entry: l.entry.WithError(err)}
}

func (l *logger) SetOutput(output io.Writer) {
	l.entry.Logger.SetOutput(output)
}

// Fields represents a map of fields for structured logging
type Fields map[string]any

// Logger defines the interface for structured logging
type Logger interface {
	Trace(msg string)
	Debug(msg string)
	Info(msg string)
	Warn(msg string)
	Error(msg string)
	Fatal(msg string)
	Panic(msg string)

	// WithField returns a new logger with an additional field for structured logging
	WithField(key string, value any) Logger
	// WithFields returns a new logger with multiple additional fields for structured logging
	WithFields(fields Fields) Logger
	// WithError returns a new logger with an error field for structured logging
	WithError(err error) Logger

	SetOutput(output io.Writer)
}

type Config struct {
	Level  string `mapstructure:"level" validate:"oneof=trace debug info warn error fatal"`
	Format string `mapstructure:"format" validate:"oneof=json text"`
	Output string `mapstructure:"output"`
}

func getLogLevel(level string) logrus.Level {
	switch strings.ToLower(level) {
	case "trace":
		return logrus.TraceLevel
	case "debug":
		return logrus.DebugLevel
	case "info":
		return logrus.InfoLevel
	case "warn":
		return logrus.WarnLevel
	case "error":
		return logrus.ErrorLevel
	default:
		return logrus.InfoLevel
	}
}

// NewLogger creates a new logger instance with the specified component name and configuration
func NewLogger(component string, cfg *Config) Logger {
	baseLogger := logrus.New()

	if cfg.Format == "json" {
		baseLogger.SetFormatter(&logrus.JSONFormatter{
			TimestampFormat: time.RFC3339Nano,
		})
	} else {
		baseLogger.SetFormatter(&logrus.TextFormatter{
			ForceColors:     true,
			FullTimestamp:   true,
			TimestampFormat: "15:04:05",
			CallerPrettyfier: func(f *runtime.Frame) (string, string) {
				filename := path.Base(f.File)
				return fmt.Sprintf("%s()", f.Function), fmt.Sprintf("%s:%d", filename, f.Line)
			},
			DisableQuote: true,
			SortingFunc: func(keys []string) {
				sort.Strings(keys)
			},
			PadLevelText: true,
		})
	}

	baseLogger.SetOutput(os.Stdout)
	baseLogger.SetLevel(getLogLevel(cfg.Level))
	entry := baseLogger.WithFields(logrus.Fields{
		"component": component,
	})

	return &logger{entry: entry}
}
