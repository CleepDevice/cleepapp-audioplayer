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

    self.refreshPlayers = function() {
        rpcService.sendCommand('get_players', 'audioplayer')
            .then((response) => {
                self.players = response.data;
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

    self.getPlaylist = function(playerId) {
        return rpcService.sendCommand('get_playlist', 'audioplayer', {
            player_uuid: playerId,
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
    $rootScope.$on('audioplayer.metadata.update', function(event, uuid, params) {
        console.log('audioplayer.metadata.update', params);
    });

    $rootScope.$on('audioplayer.playback.update', function(event, uuid, params) {
        console.log('audioplayer.playback.update', params);
        self.refreshPlayers();
    });
}]);
