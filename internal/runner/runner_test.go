package runner

import (
	"strings"
	"testing"

	"github.com/cruffinoni/update-all/internal/updater"
)

func TestExecuteCapturesCommandOutputAndExitCode(t *testing.T) {
	u := updater.Updater{Label: "TEST", Description: "fixture", Commands: []string{"printf 'hello\\n'"}, Check: func() bool { return true }, ErrorLines: 3}
	var lines []string
	got := Execute(u, &Broker{}, func(line string) { lines = append(lines, line) })
	if !got.Succeeded || got.ExitCode != 0 {
		t.Fatalf("result = %+v", got)
	}
	if !strings.Contains(got.Output, "hello") || len(lines) != 2 {
		t.Fatalf("output=%q lines=%v", got.Output, lines)
	}
}

func TestExecuteKeepsFirstNonzeroStatus(t *testing.T) {
	u := updater.Updater{Label: "TEST", Commands: []string{"exit 4", "exit 9"}, Check: func() bool { return true }}
	got := Execute(u, &Broker{}, func(string) {})
	if got.ExitCode != 4 {
		t.Fatalf("exit code = %d, want first failure 4", got.ExitCode)
	}
}

func TestExecuteAutoAnswersInteractivePrompt(t *testing.T) {
	u := updater.Updater{Label: "BREW", Commands: []string{`printf 'Proceed? [Y/n]'; read answer; printf 'answer=%s\\n' "$answer"`}, Check: func() bool { return true }, AutoAnswer: true}
	got := Execute(u, &Broker{}, func(string) {})
	if !got.Succeeded {
		t.Fatalf("command failed: %+v", got)
	}
	if !strings.Contains(got.Output, "answer=y") {
		t.Fatalf("prompt was not answered: %q", got.Output)
	}
	if strings.Contains(got.Output, "\r\ny\r\n") {
		t.Fatalf("PTY echoed its response: %q", got.Output)
	}
}
