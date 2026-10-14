package runner

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/creack/pty"
	"github.com/cruffinoni/update-all/internal/updater"
	"golang.org/x/term"
)

type Result struct {
	Label       string
	ExitCode    int
	Output      string
	Duration    time.Duration
	Succeeded   bool
	Description string
	ErrorLines  int
}

type Broker struct {
	mu       sync.Mutex
	password string
}

func (b *Broker) get(context string, reprompt bool) (string, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if reprompt {
		b.password = ""
	}
	if b.password != "" {
		return b.password, nil
	}
	fmt.Fprintln(os.Stderr, "sudo password required")
	if context != "" {
		fmt.Fprintln(os.Stderr, context)
	}
	tty, err := os.OpenFile("/dev/tty", os.O_RDWR, 0)
	if err != nil {
		return "", fmt.Errorf("open controlling terminal: %w", err)
	}
	defer tty.Close()
	fmt.Fprint(tty, "  sudo password: ")
	password, err := term.ReadPassword(int(tty.Fd()))
	fmt.Fprintln(tty)
	if err != nil {
		return "", err
	}
	b.password = string(password)
	return b.password, nil
}
func (b *Broker) cached() string { b.mu.Lock(); defer b.mu.Unlock(); return b.password }

var ansiRE = regexp.MustCompile(`\x1b\[[0-9;]*[A-Za-z]`)
var sudoPromptRE = regexp.MustCompile(`(?i)(password:|\[sudo: authenticate\] password:)\s*$`)
var rejectedRE = regexp.MustCompile(`(?i)sorry, try again\.|authentication fail(?:ure|ed)`)
var askTokenRE = regexp.MustCompile(`(?i)(\[y/n\]|\[yes/no\]|\(y/n\)|\(yes/no\))`)

func fmtDuration(d time.Duration) string {
	s := int(d.Seconds())
	h, rem := s/3600, s%3600
	m, sec := rem/60, rem%60
	if h > 0 {
		if m == 0 {
			return fmt.Sprintf("%d h", h)
		}
		return fmt.Sprintf("%d h %d min", h, m)
	}
	if m > 0 {
		if sec == 0 {
			return fmt.Sprintf("%d min", m)
		}
		return fmt.Sprintf("%d min %d s", m, sec)
	}
	return fmt.Sprintf("%d s", sec)
}

func runCommand(cmdline string, u updater.Updater, broker *Broker, emit func(string)) (string, int) {
	var output strings.Builder
	code := 0
	interactive := u.NeedsSudo || u.AutoAnswer
	command := exec.Command("bash", "-lc", cmdline)
	if interactive {
		command = exec.Command("bash", "-lc", "stty -echo 2>/dev/null; "+cmdline)
		master, err := pty.Start(command)
		if err != nil {
			return err.Error(), 1
		}
		defer master.Close()
		pending := ""
		var all strings.Builder
		answered := false
		buf := make([]byte, 4096)
		for {
			n, readErr := master.Read(buf)
			if n > 0 {
				text := strings.ReplaceAll(string(buf[:n]), "\x00", "")
				all.WriteString(text)
				pending += text
				answered = false
				for {
					i := strings.IndexAny(pending, "\r\n")
					if i < 0 {
						break
					}
					line := strings.TrimRight(pending[:i], "\r")
					delim := pending[i]
					pending = pending[i+1:]
					if delim == '\r' && strings.HasPrefix(pending, "\n") {
						pending = pending[1:]
					}
					emit(redact(line, broker))
				}
				clean := ansiRE.ReplaceAllString(pending, "")
				if u.NeedsSudo && sudoPromptRE.MatchString(clean) && !answered {
					reprompt := rejectedRE.MatchString(all.String())
					context := lastLines(all.String(), 2)
					password, pwErr := broker.get(context, reprompt)
					if pwErr != nil {
						_ = command.Process.Kill()
						return all.String() + pwErr.Error(), 1
					}
					_, _ = io.WriteString(master, password+"\n")
					answered = true
				} else if u.AutoAnswer && (askTokenRE.MatchString(clean) || regexp.MustCompile(`\?[\s:>]*$`).MatchString(clean)) && !answered {
					emit(strings.TrimSpace(clean) + " [auto-answered: y]")
					_, _ = io.WriteString(master, "y\n")
					answered = true
				}
			}
			if readErr != nil {
				break
			}
		}
		waitErr := command.Wait()
		if waitErr != nil {
			var exit *exec.ExitError
			if errors.As(waitErr, &exit) {
				code = exit.ExitCode()
			} else {
				code = 1
			}
		}
		output.WriteString(redact(all.String(), broker))
		if pending != "" && strings.TrimSpace(pending) != "" {
			emit(redact(strings.TrimRight(pending, "\r"), broker))
		}
	} else {
		stdout, err := command.StdoutPipe()
		if err != nil {
			return err.Error(), 1
		}
		command.Stderr = command.Stdout
		if err := command.Start(); err != nil {
			return err.Error(), 1
		}
		var all strings.Builder
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 4096), 2*1024*1024)
		for scanner.Scan() {
			line := scanner.Text()
			all.WriteString(line + "\n")
			emit(line)
		}
		waitErr := command.Wait()
		if waitErr != nil {
			var exit *exec.ExitError
			if errors.As(waitErr, &exit) {
				code = exit.ExitCode()
			} else {
				code = 1
			}
		}
		output.WriteString(all.String())
	}
	return output.String(), code
}

func redact(s string, broker *Broker) string {
	if broker == nil {
		return s
	}
	pw := broker.cached()
	if pw != "" {
		return strings.ReplaceAll(s, pw, "********")
	}
	return s
}
func lastLines(s string, n int) string {
	lines := strings.Split(strings.TrimSpace(s), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	return strings.Join(lines, "\n")
}

func Execute(u updater.Updater, broker *Broker, emit func(string)) Result {
	start := time.Now()
	code := 0
	var full strings.Builder
	for _, cmd := range u.Commands {
		emit("$ " + cmd)
		out, result := runCommand(cmd, u, broker, emit)
		full.WriteString(out)
		if code == 0 && result != 0 {
			code = result
		}
	}
	return Result{Label: u.Label, ExitCode: code, Output: full.String(), Duration: time.Since(start), Succeeded: code == 0, Description: u.Description, ErrorLines: u.ErrorLines}
}

func RunSequential(updaters []updater.Updater, broker *Broker, emit func(string)) []Result {
	results := []Result{}
	for _, u := range updaters {
		if !u.Check() {
			continue
		}
		results = append(results, Execute(u, broker, emit))
	}
	return results
}

func RunParallel(updaters []updater.Updater, jobs int, broker *Broker) []Result {
	active := []updater.Updater{}
	for _, u := range updaters {
		if u.Check() {
			active = append(active, u)
		}
	}
	if len(active) == 0 {
		return nil
	}
	if jobs < 1 {
		jobs = 1
	}
	if jobs > len(active) {
		jobs = len(active)
	}
	type item struct {
		index  int
		result Result
	}
	queue := make(chan int)
	done := make(chan item, len(active))
	var outputMu sync.Mutex
	for worker := 0; worker < jobs; worker++ {
		go func() {
			for i := range queue {
				u := active[i]
				r := Execute(u, broker, func(line string) {
					outputMu.Lock()
					fmt.Printf("[%s] %s\n", u.Label, line)
					outputMu.Unlock()
				})
				done <- item{i, r}
			}
		}()
	}
	go func() {
		for i := range active {
			queue <- i
		}
		close(queue)
	}()
	results := make([]Result, len(active))
	for range active {
		it := <-done
		results[it.index] = it.result
	}
	return results
}

func VerifySudo(broker *Broker, emit func(string)) error {
	u := updater.Updater{Label: "SUDO", NeedsSudo: true, Commands: []string{"sudo -k -v"}}
	for attempt := 0; attempt < 3; attempt++ {
		r := Execute(u, broker, emit)
		if r.Succeeded {
			return nil
		}
		if rejectedRE.MatchString(r.Output) {
			return fmt.Errorf("sudo rejected the password (exit %d)", r.ExitCode)
		}
		if attempt < 2 {
			time.Sleep(500 * time.Millisecond)
		}
	}
	return fmt.Errorf("sudo credential verification failed")
}

func ResultsSummary(results []Result) (int, int) {
	ok, fail := 0, 0
	for _, r := range results {
		if r.Succeeded {
			ok++
		} else {
			fail++
		}
	}
	return ok, fail
}
func PrintFailures(results []Result) {
	for _, r := range results {
		if r.Succeeded {
			continue
		}
		fmt.Printf("\n✗ %s — exit %d\n", r.Label, r.ExitCode)
		lines := strings.Split(strings.TrimRight(r.Output, "\n"), "\n")
		n := r.ErrorLines
		if n > len(lines) {
			n = len(lines)
		}
		if n > 0 {
			for _, line := range lines[len(lines)-n:] {
				fmt.Printf("  %s\n", line)
			}
		}
	}
}
func PrintSummary(results []Result, elapsed time.Duration) {
	fmt.Println()
	fmt.Printf("%-3s %-10s %9s  %s\n", "", "Tool", "Time", "Notes")
	for _, r := range results {
		icon := "✓"
		if !r.Succeeded {
			icon = "✗"
		}
		fmt.Printf("%-3s %-10s %9s  %s\n", icon, r.Label, fmtDuration(r.Duration), extractNote(r))
	}
	ok, fail := ResultsSummary(results)
	icon := "✓"
	if fail > 0 {
		icon = "✗"
	}
	fmt.Printf("%s  %d succeeded  ·  %d failed  ·  %s\n", icon, ok, fail, fmtDuration(elapsed))
}

func extractNote(r Result) string {
	if r.Output == "" {
		return "—"
	}
	out := r.Output
	patterns := map[string]*regexp.Regexp{"BREW": regexp.MustCompile(`Upgrading (\d+) (formulae?|casks?)`), "APT": regexp.MustCompile(`(\d+) upgraded`), "NPM": regexp.MustCompile(`changed (\d+) packages?`), "PNPM": regexp.MustCompile(`(\d+) packages? updated`)}
	if re := patterns[r.Label]; re != nil {
		matches := re.FindAllStringSubmatch(out, -1)
		if len(matches) > 0 {
			if r.Label == "BREW" {
				parts := []string{}
				for _, m := range matches {
					parts = append(parts, m[1]+" "+m[2])
				}
				return strings.Join(parts, ", ")
			}
			if r.Label == "NPM" {
				return matches[0][1] + " packages changed"
			}
			return matches[0][1] + " upgraded"
		}
		if r.Label == "BREW" {
			return "no upgrades"
		}
		if r.Label == "APT" {
			return "no upgrades"
		}
		return "no changes"
	}
	if !r.Succeeded {
		for _, line := range strings.Split(out, "\n") {
			if strings.Contains(strings.ToLower(line), "error:") {
				return strings.TrimSpace(line)
			}
		}
	}
	lines := 0
	for _, line := range strings.Split(out, "\n") {
		if strings.TrimSpace(line) != "" {
			lines++
		}
	}
	if lines == 0 {
		return "—"
	}
	return fmt.Sprintf("%d lines", lines)
}

func PrintVersions(emit func(string)) {
	for _, spec := range updater.VersionSpecs() {
		if !spec.Available() {
			continue
		}
		cmd := spec.VersionCommand()
		cmd.Stderr = cmd.Stdout
		output, err := cmd.Output()
		if err == nil {
			lines := strings.Split(strings.TrimSpace(string(output)), "\n")
			if len(lines) > 0 && lines[0] != "" {
				emit(fmt.Sprintf("%-12s %s", spec.Executable, lines[0]))
			}
		}
	}
}

func SortByUpdaterOrder(results []Result, updaters []updater.Updater) {
	index := map[string]int{}
	for i, u := range updaters {
		index[u.Label] = i
	}
	sort.SliceStable(results, func(i, j int) bool { return index[results[i].Label] < index[results[j].Label] })
}
func OSCommands() ([]string, bool) {
	if runtime.GOOS == "darwin" {
		return []string{"sudo softwareupdate -l", "sudo softwareupdate -ia --verbose"}, true
	}
	if runtime.GOOS == "linux" {
		return []string{"sudo apt full-upgrade -y", "sudo apt autoremove -y"}, true
	}
	return nil, false
}
func IsTerminal() bool {
	return term.IsTerminal(int(os.Stdin.Fd())) && term.IsTerminal(int(os.Stdout.Fd()))
}
func WriteOutput(w io.Writer, s string) { _, _ = io.Copy(w, bytes.NewBufferString(s)) }
