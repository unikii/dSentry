package scanner

import (
	"reflect"
	"testing"
)

func TestSplitCommandArgs(t *testing.T) {
	got, err := splitCommandArgs(`--device "sat,auto" --user='a b' -T permissive`)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"--device", "sat,auto", "--user=a b", "-T", "permissive"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("splitCommandArgs() = %#v, want %#v", got, want)
	}
}

func TestSplitCommandArgsRejectsUnterminatedQuote(t *testing.T) {
	if _, err := splitCommandArgs(`--device "sat`); err == nil {
		t.Fatal("expected unterminated quote error")
	}
}
