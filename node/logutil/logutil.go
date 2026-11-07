package logutil

import "log"

var Verbose bool

func Debugf(format string, v ...interface{}) {
	if Verbose {
		log.Printf(format, v...)
	}
}

func Debugln(v ...interface{}) {
	if Verbose {
		log.Println(v...)
	}
}
