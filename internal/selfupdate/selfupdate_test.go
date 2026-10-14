package selfupdate

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"testing"
)

func TestNewer(t *testing.T) {
	for _, tc := range []struct {
		candidate, current string
		want               bool
	}{{"2.0.11", "2.0.10", true}, {"2.1.0", "2.0.99", true}, {"2.0.10", "2.0.10", false}, {"bad", "2.0.0", false}} {
		if got := newer(tc.candidate, tc.current); got != tc.want {
			t.Errorf("newer(%q,%q)=%v want %v", tc.candidate, tc.current, got, tc.want)
		}
	}
}

func TestExtractReleaseBinary(t *testing.T) {
	var archive bytes.Buffer
	gz := gzip.NewWriter(&archive)
	tw := tar.NewWriter(gz)
	data := []byte("binary-data")
	if err := tw.WriteHeader(&tar.Header{Name: "update-all", Mode: 0o755, Size: int64(len(data)), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(data); err != nil {
		t.Fatal(err)
	}
	_ = tw.Close()
	_ = gz.Close()
	got, err := extractBinary(archive.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, data) {
		t.Fatalf("binary = %q, want %q", got, data)
	}
}
