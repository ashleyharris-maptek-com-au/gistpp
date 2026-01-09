target_types = [
  "Library", "Executable", "App", "WebFrontEnd", "Experience", "BackgroundTask", "CloudService"
]

EXECUTABLE_INTERFACE_SCHEMA = {
  "type": "object",
  "properties": {
    "output_type": {
      "type": "string",
      "enum": ["Executable"]
    },
    "description": {
      "type": "string"
    },
    "schema": {
      "type": "object",
      "properties": {
        "positional_args": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string"
              },
              "type": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "optional": {
                "type": "boolean"
              },
            }
          }
        },
        "flags": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string"
              },
              "short": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "takes_value": {
                "type": "boolean"
              },
            }
          }
        },
        "stdin": {
          "type": "object"
        },
        "stdout": {
          "type": "object"
        },
        "stderr": {
          "type": "object"
        },
        "exit_codes": {
          "type": "object",
          "additionalProperties": {
            "type": "string"
          }
        },
      }
    }
  }
}

LIBRARY_INTERFACE_SCHEMA = {
  "type": "object",
  "properties": {
    "output_type": {
      "type": "string",
      "enum": ["Library"]
    },
    "description": {
      "type": "string"
    },
    "schema": {
      "type": "object",
      "properties": {
        "types": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": {
                "type": "string",
                "enum": ["Struct", "Class", "Enum"]
              },
              "name": {
                "type": "string"
              },
              "fields": {
                "type": "array"
              },
              "methods": {
                "type": "array",
                "items": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": "string"
                      },
                      "args": {
                        "type": "array"
                      },
                      "returns": {
                        "type": "string"
                      },
                      "description": {
                        "type": "string"
                      },
                    }
                  }
                }
              },
            }
          }
        },
        "functions": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string"
              },
              "args": {
                "type": "array"
              },
              "returns": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
            }
          }
        },
        "constants": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string"
              },
              "type": {
                "type": "string"
              },
              "value": {},
            }
          }
        },
        "operators": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": {
                "type": "string"
              },
              "name": {
                "type": "string"
              },
              "args": {
                "type": "array"
              },
              "returns": {
                "type": "string"
              },
            }
          }
        },
      }
    }
  }
}

TEST_SCHEMA = {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "name": {
        "type": "string",
        "description": "Valid identifier - Test_[A-Za-z][A-Za-z0-9_]*"
      },
      "description": {
        "type": "string",
        "description": "~10 word description of the test"
      },
      "pseudocode": {
        "type":
        "string",
        "description":
        "Pseudocode of the test with enough detail to be implemented by a junior developer."
      },
      "type": {
        "type":
        "string",
        "enum": ["contract", "unit", "integration", "edge"],
        "description":
        """
- contract: Tests that are either requested by the user as part of the spec, 
            or otherwise fundamental behavior that should be fixed within a major version.
- unit: Tests a single function or method in isolation, but not part of the specification contract.
- integration: Tests how multiple features interact.
- edge: An obscure corner case, bug reported in the wild, or something added to get full test coverage.
                    """
      },
    },
    "required": ["name", "description", "pseudocode", "type"]
  }
}
