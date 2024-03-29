/**
 * Audioplayer service.
 * Handle audioplayer application requests.
 * Service is the place to store your application content (it is a singleton) and
 * to provide your application functions.
 */
angular
.module('Cleep')
.service('audioplayerService', ['$rootScope', 'rpcService',
function($rootScope, rpcService) {
    var self = this;
    self.players = [];
    self.playlist = {};
    self.playlistPlayerId = null;

    self.refreshPlayers = function() {
        return rpcService.sendCommand('get_players', 'audioplayer')
            .then((response) => {
                if (response.error) return;
                self.players = response.data;
                return response;
            });
    };

    self.play = function(resource, audioFormat) {
        return rpcService.sendCommand('start_playback', 'audioplayer', {
            resource: resource,
            audio_format: audioFormat,
        });
    };

    self.pause = function(playerId) {
        return rpcService.sendCommand('pause_playback', 'audioplayer', {
            player_uuid: playerId,
        });
    };

    self.stop = function(playerId) {
        return rpcService.sendCommand('stop_playback', 'audioplayer', {
            player_uuid: playerId,
        });
    };

    self.next = function(playerId) {
        return rpcService.sendCommand('play_next_track', 'audioplayer', {
            player_uuid: playerId,
        });
    };

    self.previous = function(playerId) {
        return rpcService.sendCommand('play_previous_track', 'audioplayer', {
            player_uuid: playerId,
        });
    };

    self.setVolume = function(playerId, volume) {
        return rpcService.sendCommand('set_volume', 'audioplayer', {
            player_uuid: playerId,
            volume: volume,
        });
    };

    self.setRepeat = function(playerId, repeat) {
        return rpcService.sendCommand('set_repeat', 'audioplayer', {
            player_uuid: playerId,
            repeat: repeat,
        });
    };

    self.shufflePlaylist = function(playerId, repeat) {
        return rpcService.sendCommand('shuffle_playlist', 'audioplayer', {
            player_uuid: playerId,
        });
    };

    self.getPlaylist = function(playerId) {
        return rpcService.sendCommand('get_playlist', 'audioplayer', {
            player_uuid: playerId,
        })
            .then((response) => {
                if (response.error) return;
                self.playlistPlayerId = playerId;
                Object.assign(self.playlist, response.data);
                return response;
            });
    };

    self.addTrack = function(playerId, resource, audioFormat, trackIndex) {
        return rpcService.sendCommand('add_track', 'audioplayer', {
            player_uuid: playerId,
            resource: resource,
            audio_format: audioFormat,
            track_index: trackIndex,
        });
    };

    self.removeTrack = function(playerId, trackIndex) {
        return rpcService.sendCommand('remove_track', 'audioplayer', {
            player_uuid: playerId,
            track_index: trackIndex,
        });
    };

    /**
     * Catch events
     */
    $rootScope.$on('audioplayer.playback.update', function(event, uuid, params) {
        // update playlist
        if (Object.keys(self.playlist).length) {
            self.playlist.index = params.index;
        }

        // delete non running player
        if (params.state === 'stopped') {
            for (var i=0; i<self.players.length; i++) {
                if (self.players[i].playeruuid === params.playeruuid) {
                    self.players.splice(i, 1);
                    // clear playlist
                    if (params.playeruuid === self.playlistPlayerId) {
                        self.playlistPlayerId = null;
                        Object.keys(self.playlist).forEach(key => {
                            delete self.playlist[key];
                        });
                    }
                    break;
                }
            }
            return;
        }

        // update existing player
        let found = false;
        for (const player of self.players) {
            if (player.playeruuid === params.playeruuid) {
                Object.assign(player, params);
                found = true;
                break;
            }
        }

        // add new player
        if (!found) {
            self.players.push(params);
        }
    });
}]);
