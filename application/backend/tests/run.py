"""Dependency-free unittest runner with GitLab JUnit evidence."""

import sys
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class Result(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()

    def stopTest(self, test):
        case = ET.SubElement(
            self.suite, "testcase", name=test.id(), time=str(time.monotonic() - self.started)
        )
        for tag, records in (("failure", self.failures), ("error", self.errors)):
            for item, detail in records:
                if item == test:
                    ET.SubElement(case, tag).text = detail
        for item, reason in self.skipped:
            if item == test:
                ET.SubElement(case, "skipped").text = reason
        super().stopTest(test)


if __name__ == "__main__":
    Result.suite = ET.Element("testsuite", name="mrp-app")
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    Result.suite.set("tests", str(result.testsRun))
    Result.suite.set("failures", str(len(result.failures)))
    Result.suite.set("errors", str(len(result.errors)))
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    ET.ElementTree(Result.suite).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
    sys.exit(0 if result.wasSuccessful() else 1)
