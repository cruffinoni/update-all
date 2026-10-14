package selfupdate

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"golang.org/x/term"
)

const Repo = "cruffinoni/update-all"
const DeclinedPath = ".cache/update-all/declined-version"
const SkipEnv = "UPDATE_ALL_NO_SELF_UPDATE"

type release struct {
	TagName string  `json:"tag_name"`
	Assets  []asset `json:"assets"`
}
type asset struct {
	Name string `json:"name"`
	URL  string `json:"browser_download_url"`
}

var httpClient = &http.Client{Timeout: 8 * time.Second}

func Latest() (*release, error) {
	req, _ := http.NewRequest(http.MethodGet, "https://api.github.com/repos/"+Repo+"/releases/latest", nil)
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "update-all")
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GitHub returned %s", resp.Status)
	}
	var r release
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return nil, err
	}
	return &r, nil
}

func Version(tag string) string { return strings.TrimPrefix(tag, "v") }
func newer(candidate, current string) bool {
	parse := func(s string) ([]int, bool) {
		parts := strings.Split(strings.TrimPrefix(s, "v"), ".")
		out := make([]int, len(parts))
		for i, p := range parts {
			n, e := strconv.Atoi(p)
			if e != nil {
				return nil, false
			}
			out[i] = n
		}
		return out, len(parts) > 0
	}
	a, ok := parse(candidate)
	if !ok {
		return false
	}
	b, ok := parse(current)
	if !ok {
		return false
	}
	for i := 0; i < len(a) || i < len(b); i++ {
		av, bv := 0, 0
		if i < len(a) {
			av = a[i]
		}
		if i < len(b) {
			bv = b[i]
		}
		if av > bv {
			return true
		}
		if av < bv {
			return false
		}
	}
	return false
}

func declinedPath() string { home, _ := os.UserHomeDir(); return filepath.Join(home, DeclinedPath) }
func declinedVersion() string {
	data, err := os.ReadFile(declinedPath())
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}
func markDeclined(version string) error {
	path := declinedPath()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(version), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
func MarkDeclined(version string) error { return markDeclined(version) }

func AskUpdate(current string) (bool, string) {
	if os.Getenv(SkipEnv) != "" || !IsInteractive() {
		return false, ""
	}
	r, err := Latest()
	if err != nil {
		return false, ""
	}
	latest := Version(r.TagName)
	if !newer(latest, current) {
		return false, ""
	}
	declined := declinedVersion()
	if declined != "" && !newer(latest, declined) {
		return false, ""
	}
	tty, err := os.OpenFile("/dev/tty", os.O_RDWR, 0)
	if err != nil {
		return false, ""
	}
	defer tty.Close()
	fmt.Fprintf(tty, "[update-all] Version %s is available (current %s). Update now? [Y/n] ", latest, current)
	var answer string
	_, _ = fmt.Fscanln(tty, &answer)
	if answer == "" || strings.EqualFold(answer, "y") || strings.EqualFold(answer, "yes") {
		return true, ""
	}
	return false, latest
}
func IsInteractive() bool {
	return term.IsTerminal(int(os.Stdin.Fd())) && term.IsTerminal(int(os.Stdout.Fd()))
}

func Update() error {
	r, err := Latest()
	if err != nil {
		return fmt.Errorf("could not find latest GitHub release: %w", err)
	}
	archiveName := fmt.Sprintf("update-all_%s_%s_%s.tar.gz", Version(r.TagName), runtime.GOOS, runtime.GOARCH)
	var archiveURL, checksumsURL string
	for _, a := range r.Assets {
		if a.Name == archiveName {
			archiveURL = a.URL
		}
		if strings.Contains(a.Name, "checksums") {
			checksumsURL = a.URL
		}
	}
	if archiveURL == "" || checksumsURL == "" {
		return fmt.Errorf("release %s is missing an archive or checksum asset for %s/%s", r.TagName, runtime.GOOS, runtime.GOARCH)
	}
	archive, err := download(archiveURL)
	if err != nil {
		return err
	}
	checksums, err := download(checksumsURL)
	if err != nil {
		return err
	}
	expected := ""
	for _, line := range strings.Split(string(checksums), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && fields[1] == archiveName {
			expected = fields[0]
		}
	}
	if expected == "" {
		return errors.New("checksum file does not contain the selected archive")
	}
	sum := sha256.Sum256(archive)
	if hex.EncodeToString(sum[:]) != expected {
		return errors.New("release archive checksum verification failed")
	}
	bin, err := extractBinary(archive)
	if err != nil {
		return err
	}
	return replaceExecutable(bin)
}

func download(url string) ([]byte, error) {
	req, _ := http.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("User-Agent", "update-all")
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("download failed: %s", resp.Status)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 128<<20))
}
func extractBinary(data []byte) ([]byte, error) {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	for {
		h, e := tr.Next()
		if e == io.EOF {
			break
		}
		if e != nil {
			return nil, e
		}
		if filepath.Base(h.Name) == "update-all" && h.Typeflag == tar.TypeReg {
			return io.ReadAll(io.LimitReader(tr, 64<<20))
		}
	}
	return nil, errors.New("release archive does not contain update-all binary")
}
func replaceExecutable(data []byte) error {
	path, err := os.Executable()
	if err != nil {
		return err
	}
	path, err = filepath.EvalSymlinks(path)
	if err != nil {
		return err
	}
	mode := os.FileMode(0o755)
	if info, e := os.Stat(path); e == nil {
		mode = info.Mode().Perm()
	}
	tmp := path + ".new"
	if err := os.WriteFile(tmp, data, mode); err != nil {
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}
